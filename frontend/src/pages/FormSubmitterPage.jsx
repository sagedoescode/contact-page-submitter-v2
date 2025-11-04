// src/pages/FormSubmitterPage.jsx - Complete Fixed Version
import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { 
  Upload, FileText, Send, AlertCircle, CheckCircle2, 
  ArrowLeft, Target, Globe, Clock, BarChart3, X, User
} from 'lucide-react';
import { toast } from 'react-hot-toast';
import apiService from '../services/api';

const FormSubmitterPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const editId = searchParams.get('edit');
  const cloneId = searchParams.get('clone');
  
  const [formData, setFormData] = useState({
    campaign_name: '',
    csv_file: null,
    csv_filename: '',
    message_template: '',
    form_selector: '',
    fallback_email: '',
    max_retries: 3,
    proxy_rotation: true,
    captcha_solving: true,
    delay_between_submissions: 5
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [validationErrors, setValidationErrors] = useState({});
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);
  const [processingCampaignId, setProcessingCampaignId] = useState(null);
  const [campaignStatus, setCampaignStatus] = useState(null);
  const [statusCheckErrors, setStatusCheckErrors] = useState(0);
  const [userProfile, setUserProfile] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);

  // Load user profile data on component mount
  useEffect(() => {
    fetchUserProfile();
  }, []);

  // Load campaign data if editing or cloning
  useEffect(() => {
    if (editId || cloneId) {
      loadCampaignData(editId || cloneId);
    }
  }, [editId, cloneId]);

  // Enhanced status polling with error recovery
  useEffect(() => {
    let statusInterval = null;
    
    if (processingCampaignId && !campaignStatus?.is_complete) {
      statusInterval = setInterval(async () => {
        try {
          console.log(`Checking status for campaign ${processingCampaignId}`);
          const status = await apiService.getCampaignStatus(processingCampaignId);
          console.log('Campaign status:', status);
          
          setCampaignStatus(status);
          setStatusCheckErrors(0); // Reset error counter on success
          
          // Handle completion states
          if (status.is_complete) {
            clearInterval(statusInterval);
            setProcessingCampaignId(null);
            
            if (status.status === 'COMPLETED') {
              setSuccess(true);
              toast.success('Campaign completed successfully!');
              setTimeout(() => {
                navigate(`/campaigns/${processingCampaignId}`);
              }, 2000);
            } else if (status.status === 'FAILED') {
              const errorMsg = status.error_message || 'Campaign processing failed';
              setError(errorMsg);
              toast.error(errorMsg);
            } else if (status.status === 'STOPPED') {
              toast.info('Campaign was stopped');
              navigate(`/campaigns/${processingCampaignId}`);
            }
          }
        } catch (err) {
          console.error('Status check error:', err);
          setStatusCheckErrors(prev => prev + 1);
          
          // Stop polling after too many errors
          if (statusCheckErrors >= 10) {
            clearInterval(statusInterval);
            setError('Lost connection to campaign processing. Please check campaign list.');
            toast.error('Connection lost. Please check campaign status manually.');
          }
        }
      }, 2000); // Poll every 2 seconds
    }
    
    return () => {
      if (statusInterval) {
        clearInterval(statusInterval);
      }
    };
  }, [processingCampaignId, campaignStatus?.is_complete, statusCheckErrors, navigate]);

  const fetchUserProfile = async () => {
    try {
      setProfileLoading(true);
      const response = await apiService.getUserProfile();
      
      // API returns {user: {...}, profile: {...}}, merge them
      const userData = response.user || {};
      const profileData = response.profile || {};
      
      // Combine user and profile data into a single object
      const mergedProfile = {
        ...userData,
        ...profileData,
        // Ensure we have the email from user if not in profile
        email: userData.email || profileData.email,
        first_name: userData.first_name || profileData.first_name,
        last_name: userData.last_name || profileData.last_name,
      };
      
      setUserProfile(mergedProfile);
      
      // Pre-populate form fields with user profile data
      if (mergedProfile) {
        // Get user's full name for placeholder
        const fullName = [mergedProfile.first_name, mergedProfile.last_name]
          .filter(Boolean)
          .join(' ') || 'Your Name';
        
        setFormData(prev => ({
          ...prev,
          message_template: mergedProfile.message || prev.message_template || `Hi {name},\n\nI wanted to reach out regarding {topic}...`,
          fallback_email: mergedProfile.email || prev.fallback_email
        }));
      }
    } catch (err) {
      console.error('Error loading user profile:', err);
      // Don't show error toast for profile loading as it's not critical
    } finally {
      setProfileLoading(false);
    }
  };

  const loadCampaignData = async (campaignId) => {
    try {
      const campaign = await apiService.getCampaign(campaignId);
      setFormData({
        ...formData,
        campaign_name: cloneId ? `${campaign.name} (Copy)` : campaign.name,
        message_template: campaign.message || '',
        form_selector: campaign.settings?.form_selector || '',
        fallback_email: campaign.settings?.fallback_email || '',
        max_retries: campaign.settings?.max_retries || 3,
        proxy_rotation: campaign.settings?.proxy_rotation !== false,
        captcha_solving: campaign.settings?.captcha_solving !== false,
        delay_between_submissions: campaign.settings?.delay_between_submissions || 5
      });
    } catch (err) {
      console.error('Error loading campaign:', err);
      toast.error('Failed to load campaign data');
      setError('Failed to load campaign data');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setSuccess(false);
    setValidationErrors({});
    
    // Validate form
    const errors = {};
    if (!formData.campaign_name.trim()) {
      errors.campaign_name = 'Campaign name is required';
    }
    if (!editId && !formData.csv_file) {
      errors.csv_file = 'CSV file is required';
    }
    if (!formData.message_template.trim()) {
      errors.message_template = 'Message template is required';
    }
    
    if (Object.keys(errors).length > 0) {
      setValidationErrors(errors);
      setIsSubmitting(false);
      return;
    }
    
    try {
      if (editId) {
        // Update existing campaign
        await apiService.updateCampaign(editId, {
          name: formData.campaign_name,
          message: formData.message_template,
          settings: {
            form_selector: formData.form_selector,
            fallback_email: formData.fallback_email,
            max_retries: formData.max_retries,
            proxy_rotation: formData.proxy_rotation,
            captcha_solving: formData.captcha_solving,
            delay_between_submissions: formData.delay_between_submissions
          }
        });
        
        toast.success('Campaign updated successfully');
        navigate(`/campaigns/${editId}`);
      } else {
        // Create new campaign
        console.log('Starting campaign with CSV...');
        const result = await apiService.startCampaignWithCSV(formData.csv_file, {
          name: formData.campaign_name,
          message: formData.message_template,
          proxy: formData.proxy_rotation ? 'enabled' : '',
          use_captcha: formData.captcha_solving,
          settings: {
            form_selector: formData.form_selector,
            fallback_email: formData.fallback_email,
            max_retries: formData.max_retries,
            proxy_rotation: formData.proxy_rotation,
            captcha_solving: formData.captcha_solving,
            delay_between_submissions: formData.delay_between_submissions
          }
        });
        
        console.log('Campaign start result:', result);
        
        if (result.success && result.campaign_id) {
          setProcessingCampaignId(result.campaign_id);
          setCampaignStatus({
            campaign_id: result.campaign_id,
            total: result.total_urls || 0,
            processed: 0,
            successful: 0,
            failed: 0,
            status: 'PROCESSING',
            progress_percent: 0,
            is_complete: false
          });
          setUploadProgress(100);
          toast.success(`Campaign started with ${result.total_urls} URLs`);
        } else {
          throw new Error(result.message || result.detail || 'Failed to start campaign');
        }
      }
    } catch (err) {
      console.error('Error starting campaign:', err);
      const errorMessage = err.response?.data?.detail || err.message || 'Failed to start campaign';
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (file) {
      // Validate file type
      if (!file.name.toLowerCase().endsWith('.csv')) {
        setValidationErrors({ ...validationErrors, csv_file: 'File must be a CSV' });
        toast.error('Please select a CSV file');
        return;
      }
      
      // Validate file size
      if (file.size > 10 * 1024 * 1024) {
        setValidationErrors({ ...validationErrors, csv_file: 'File size must be less than 10MB' });
        toast.error('File size must be less than 10MB');
        return;
      }
      
      setFormData({
        ...formData,
        csv_file: file,
        csv_filename: file.name
      });
      setValidationErrors({ ...validationErrors, csv_file: null });
      
      // Simulate upload progress
      setUploadProgress(0);
      let progress = 0;
      const interval = setInterval(() => {
        progress += 20;
        setUploadProgress(progress);
        if (progress >= 100) {
          clearInterval(interval);
          toast.success('File uploaded successfully');
        }
      }, 100);
    }
  };

  const getStatusColor = (status) => {
    const colors = {
      'PROCESSING': 'text-blue-700 bg-blue-100',
      'RUNNING': 'text-green-700 bg-green-100',
      'COMPLETED': 'text-green-700 bg-green-100',
      'FAILED': 'text-red-700 bg-red-100',
      'STOPPED': 'text-gray-700 bg-gray-100',
      'PAUSED': 'text-yellow-700 bg-yellow-100'
    };
    return colors[status] || 'text-gray-700 bg-gray-100';
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 p-6">
      {/* Header Navigation */}
      <div className="max-w-7xl mx-auto mb-8">
        <div className="flex items-center justify-between bg-white rounded-xl shadow-sm p-4">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/campaigns')}
              className="flex items-center gap-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
              <span>Back to Campaigns</span>
            </button>
            <div className="h-6 w-px bg-gray-300" />
            <h1 className="text-2xl font-bold text-gray-900">
              {editId ? 'Edit Campaign' : cloneId ? 'Clone Campaign' : 'Create New Campaign'}
            </h1>
          </div>
          
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/campaigns')}
              className="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              View All Campaigns
            </button>
            <button
              onClick={() => navigate('/reports')}
              className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
            >
              <BarChart3 className="w-4 h-4" />
              Analytics
            </button>
          </div>
        </div>
      </div>

      {/* Success Alert */}
      {success && (
        <div className="max-w-4xl mx-auto mb-6">
          <div className="bg-green-50 border border-green-200 rounded-xl p-6">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="w-6 h-6 text-green-600 flex-shrink-0" />
              <div>
                <h3 className="font-semibold text-green-900">Campaign Completed Successfully!</h3>
                <p className="text-green-700">Redirecting to campaign details...</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Campaign Processing Status */}
      {campaignStatus && !success && (
        <div className="max-w-4xl mx-auto mb-6">
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-blue-900">Campaign Processing</h3>
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(campaignStatus.status)}`}>
                {campaignStatus.status}
              </span>
            </div>
            
            <div className="grid grid-cols-4 gap-4 mb-4">
              <div>
                <p className="text-sm text-blue-600">Total URLs</p>
                <p className="text-2xl font-bold text-blue-900">{campaignStatus.total || 0}</p>
              </div>
              <div>
                <p className="text-sm text-blue-600">Processed</p>
                <p className="text-2xl font-bold text-blue-900">{campaignStatus.processed || 0}</p>
              </div>
              <div>
                <p className="text-sm text-green-600">Successful</p>
                <p className="text-2xl font-bold text-green-700">{campaignStatus.successful || 0}</p>
              </div>
              <div>
                <p className="text-sm text-red-600">Failed</p>
                <p className="text-2xl font-bold text-red-700">{campaignStatus.failed || 0}</p>
              </div>
            </div>
            
            <div className="w-full bg-blue-100 rounded-full h-4 overflow-hidden">
              <div 
                className="bg-gradient-to-r from-blue-500 to-blue-600 h-4 rounded-full transition-all duration-500 ease-out"
                style={{ width: `${Math.min(campaignStatus.progress_percent || 0, 100)}%` }}
              />
            </div>
            
            <div className="mt-3 text-sm text-blue-700">
              Processing {campaignStatus.processed || 0} of {campaignStatus.total || 0} URLs 
              ({Math.round(campaignStatus.progress_percent || 0)}% complete)
            </div>
          </div>
        </div>
      )}

      {/* Error Alert */}
      {error && (
        <div className="max-w-4xl mx-auto mb-6">
          <div className="bg-red-50 border border-red-200 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />
                <p className="text-red-700">{error}</p>
              </div>
              <button 
                onClick={() => setError(null)}
                className="text-red-600 hover:text-red-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Form Container */}
      <div className="max-w-4xl mx-auto">
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Campaign Details Card */}
          <div className="bg-white rounded-xl shadow-sm p-6">
            <div className="flex items-center gap-3 mb-6">
              <Target className="w-6 h-6 text-blue-600" />
              <h2 className="text-xl font-semibold text-gray-900">Campaign Details</h2>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Campaign Name *
                </label>
                <input
                  type="text"
                  value={formData.campaign_name}
                  onChange={(e) => setFormData({...formData, campaign_name: e.target.value})}
                  className="w-full px-4 py-3 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                  placeholder="e.g., Q1 2025 Outreach Campaign"
                  required
                />
                {validationErrors.campaign_name && (
                  <p className="mt-1 text-sm text-red-600">{validationErrors.campaign_name}</p>
                )}
              </div>

              {/* Only show file upload for new campaigns */}
              {!editId && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Upload CSV File *
                  </label>
                  <div className="relative">
                    <input
                      type="file"
                      accept=".csv"
                      onChange={handleFileUpload}
                      className="hidden"
                      id="csv-upload"
                      required={!editId}
                    />
                    <label
                      htmlFor="csv-upload"
                      className="flex items-center justify-center w-full px-4 py-8 border-2 border-dashed border-gray-300 rounded-lg hover:border-blue-500 cursor-pointer transition-colors"
                    >
                      <div className="text-center">
                        <Upload className="w-12 h-12 mx-auto text-gray-400 mb-3" />
                        <p className="text-sm text-gray-600">
                          {formData.csv_filename || 'Click to upload or drag and drop'}
                        </p>
                        <p className="text-xs text-gray-500 mt-1">CSV files only (max 10MB)</p>
                      </div>
                    </label>
                    
                    {uploadProgress > 0 && uploadProgress < 100 && (
                      <div className="mt-3">
                        <div className="flex items-center justify-between text-sm text-gray-600 mb-1">
                          <span>Uploading...</span>
                          <span>{uploadProgress}%</span>
                        </div>
                        <div className="w-full bg-gray-200 rounded-full h-2">
                          <div 
                            className="bg-gradient-to-r from-blue-500 to-blue-600 h-2 rounded-full transition-all duration-300"
                            style={{ width: `${uploadProgress}%` }}
                          />
                        </div>
                      </div>
                    )}
                    
                    {uploadProgress === 100 && formData.csv_file && (
                      <div className="mt-3 flex items-center gap-2 text-green-600">
                        <CheckCircle2 className="w-4 h-4" />
                        <span className="text-sm">File ready: {formData.csv_filename}</span>
                      </div>
                    )}
                    
                    {validationErrors.csv_file && (
                      <p className="mt-1 text-sm text-red-600">{validationErrors.csv_file}</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* User Profile Information */}
          {(userProfile || profileLoading) && (
            <div className="bg-white rounded-xl shadow-sm p-6">
              <div className="flex items-center gap-3 mb-6">
                <User className="w-6 h-6 text-indigo-600" />
                <h2 className="text-xl font-semibold text-gray-900">Your Profile Information</h2>
                {profileLoading && (
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <div className="w-4 h-4 border-2 border-gray-300 border-t-indigo-600 rounded-full animate-spin"></div>
                    <span>Loading...</span>
                  </div>
                )}
              </div>
              
              {profileLoading && !userProfile ? (
                <div className="text-center py-8 text-gray-500">
                  <div className="w-8 h-8 border-2 border-gray-300 border-t-indigo-600 rounded-full animate-spin mx-auto mb-2"></div>
                  <p>Loading profile information...</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-gray-500">Name</label>
                    <p className="text-sm text-gray-900 font-medium">
                      {userProfile 
                        ? ([userProfile.first_name, userProfile.last_name].filter(Boolean).join(' ') || 'Not set')
                        : 'Loading...'}
                    </p>
                  </div>
                  
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-gray-500">Email</label>
                    <p className="text-sm text-gray-900 font-medium">
                      {userProfile ? (userProfile.email || 'Not set') : 'Loading...'}
                    </p>
                  </div>
                  
                  {userProfile?.company_name && (
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-gray-500">Company</label>
                      <p className="text-sm text-gray-900">{userProfile.company_name}</p>
                    </div>
                  )}
                  
                  {userProfile?.job_title && (
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-gray-500">Job Title</label>
                      <p className="text-sm text-gray-900">{userProfile.job_title}</p>
                    </div>
                  )}
                  
                  {userProfile?.phone_number && (
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-gray-500">Phone</label>
                      <p className="text-sm text-gray-900">{userProfile.phone_number}</p>
                    </div>
                  )}
                  
                  {userProfile?.website_url && (
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-gray-500">Website</label>
                      <p className="text-sm text-gray-900">{userProfile.website_url}</p>
                    </div>
                  )}
                </div>
              )}
              
              <div className="mt-4 p-3 bg-blue-50 rounded-lg">
                <p className="text-sm text-blue-800">
                  <strong>Note:</strong> This information will be used to automatically fill contact forms when your campaign runs. 
                  You can update your profile in the <a href="/profile" className="text-blue-600 hover:text-blue-800 underline">Profile Settings</a> page.
                </p>
              </div>
            </div>
          )}

          {/* Message Configuration */}
          <div className="bg-white rounded-xl shadow-sm p-6">
            <div className="flex items-center gap-3 mb-6">
              <FileText className="w-6 h-6 text-purple-600" />
              <h2 className="text-xl font-semibold text-gray-900">Message Configuration</h2>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Message Template *
                </label>
                <textarea
                  value={formData.message_template}
                  onChange={(e) => setFormData({...formData, message_template: e.target.value})}
                  className="w-full px-4 py-3 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                  rows="6"
                  placeholder={(() => {
                    const fullName = userProfile 
                      ? [userProfile.first_name, userProfile.last_name].filter(Boolean).join(' ') 
                      : null;
                    if (fullName) {
                      return `Hi {name},\n\nI'm ${fullName} and I wanted to reach out regarding {topic}...`;
                    }
                    return `Hi {name},\n\nI wanted to reach out regarding {topic}...`;
                  })()}
                  required
                />
                <p className="mt-1 text-xs text-gray-500">
                  Use {'{'}name{'}'}, {'{'}company{'}'}, etc. for dynamic fields from your CSV
                </p>
                {validationErrors.message_template && (
                  <p className="mt-1 text-sm text-red-600">{validationErrors.message_template}</p>
                )}
              </div>
            </div>
          </div>

          {/* Advanced Settings */}
          <div className="bg-white rounded-xl shadow-sm p-6">
            <div className="flex items-center gap-3 mb-6">
              <Globe className="w-6 h-6 text-green-600" />
              <h2 className="text-xl font-semibold text-gray-900">Advanced Settings</h2>
            </div>
            
            <div className="grid grid-cols-2 gap-6">
              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
                <label className="text-sm font-medium text-gray-700">
                  Enable Proxy Rotation
                </label>
                <input
                  type="checkbox"
                  checked={formData.proxy_rotation}
                  onChange={(e) => setFormData({...formData, proxy_rotation: e.target.checked})}
                  className="w-5 h-5 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
                />
              </div>
              
              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
                <label className="text-sm font-medium text-gray-700">
                  Enable CAPTCHA Solving
                </label>
                <input
                  type="checkbox"
                  checked={formData.captcha_solving}
                  onChange={(e) => setFormData({...formData, captcha_solving: e.target.checked})}
                  className="w-5 h-5 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>

          {/* Form Actions */}
          <div className="flex items-center justify-between bg-white rounded-xl shadow-sm p-6">
            <button
              type="button"
              onClick={() => navigate('/campaigns')}
              className="px-6 py-3 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
            >
              Cancel
            </button>
            
            <button
              type="submit"
              disabled={isSubmitting || !!processingCampaignId}
              className="flex items-center gap-2 px-8 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-lg hover:from-blue-700 hover:to-indigo-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? (
                <>
                  <Clock className="w-5 h-5 animate-spin" />
                  {editId ? 'Updating...' : 'Starting Campaign...'}
                </>
              ) : processingCampaignId ? (
                <>
                  <Clock className="w-5 h-5 animate-spin" />
                  Processing...
                </>
              ) : (
                <>
                  <Send className="w-5 h-5" />
                  {editId ? 'Update Campaign' : 'Start Campaign'}
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default FormSubmitterPage;