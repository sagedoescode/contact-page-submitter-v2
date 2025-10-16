import React, { useState, useEffect, useRef, useCallback } from "react";
import { 
  DollarSign, Users, TrendingUp, UserPlus, CreditCard, Shield, Activity, 
  Settings, Mail, Globe, AlertCircle, CheckCircle, Clock, FileText, 
  ChevronDown, MoreVertical, Eye, Edit, Pause, Play, RefreshCw, Zap,
  BarChart3, Target, Calendar, Award, Briefcase, Send, Loader2, X
} from "lucide-react";

const OwnerDashboard = () => {
  // Basic state
  const [selectedPeriod, setSelectedPeriod] = useState("month");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showNotification, setShowNotification] = useState(false);
  const [notificationMessage, setNotificationMessage] = useState('');
  const [notificationType, setNotificationType] = useState('success');
  
  // Data state
  const [stats, setStats] = useState([]);
  const [revenueData, setRevenueData] = useState([]);
  const [subscriptionData, setSubscriptionData] = useState([]);
  const [teamMembers, setTeamMembers] = useState([]);
  const [customerActivity, setCustomerActivity] = useState([]);
  const [systemMetrics, setSystemMetrics] = useState({
    totalCampaigns: 0,
    activeCSVs: 0,
    avgSuccessRate: 0,
    totalSubmissions: "0",
    serverLoad: 0
  });
  const [recentTransactions, setRecentTransactions] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  
  // Team management state
  const [showAddMemberModal, setShowAddMemberModal] = useState(false);
  const [showEditMemberModal, setShowEditMemberModal] = useState(false);
  const [selectedMember, setSelectedMember] = useState(null);
  const [newMemberData, setNewMemberData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    role: 'user',
    password: ''
  });

  // CRITICAL FIX: Add refs to prevent duplicate requests
  const abortControllerRef = useRef(null);
  const isLoadingRef = useRef(false);
  const lastFetchTimeRef = useRef(0);
  const mountedRef = useRef(true);

  // API base URL
  const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  // Helper function to show notifications
  const displayNotification = useCallback((message, type = 'success') => {
    if (!mountedRef.current) return;
    setNotificationMessage(message);
    setNotificationType(type);
    setShowNotification(true);
    setTimeout(() => {
      if (mountedRef.current) {
        setShowNotification(false);
      }
    }, 3000);
  }, []);

  // FIXED API call function with request deduplication
  const fetchAPI = useCallback(async (endpoint, options = {}) => {
    const token = localStorage.getItem('access_token');
    const fullUrl = `${API_BASE_URL}${endpoint}`;
    
    // Use the abort controller from the current request batch
    const controller = abortControllerRef.current;
    
    console.log(`📡 API Call: ${fullUrl}`);
    
    try {
      const response = await fetch(fullUrl, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': token ? `Bearer ${token}` : '',
          ...options.headers
        },
        signal: controller?.signal // Add abort signal
      });

      console.log(`📡 Response Status: ${response.status} for ${endpoint}`);

      if (!response.ok) {
        if (response.status === 401) {
          console.error('🔒 Authentication failed');
          localStorage.removeItem('access_token');
          window.location.href = '/';
          throw new Error('Authentication required');
        }
        throw new Error(`API Error: ${response.status} - ${response.statusText}`);
      }

      const text = await response.text();
      console.log(`📦 Response Size: ${text.length} bytes for ${endpoint}`);
      
      if (!text) {
        console.warn(`⚠️ Empty response from ${endpoint}`);
        return null;
      }

      const jsonData = JSON.parse(text);
      console.log(`✅ Parsed data for ${endpoint}:`, jsonData);
      return jsonData;
    } catch (error) {
      if (error.name === 'AbortError') {
        console.log(`🛑 Request aborted: ${endpoint}`);
        return null; // Don't throw for aborted requests
      }
      console.error(`❌ Error calling ${endpoint}:`, error);
      throw error;
    }
  }, [API_BASE_URL]);

  // Helper function to convert period to days
  const getDaysFromPeriod = useCallback((period) => {
    switch (period) {
      case 'today': return 1;
      case 'week': return 7;
      case 'month': return 30;
      case 'year': return 365;
      default: return 30;
    }
  }, []);

  // FIXED - Prevent duplicate requests with proper state management
  const fetchDashboardData = useCallback(async (forceRefresh = false) => {
    // Prevent duplicate requests
    const now = Date.now();
    const timeSinceLastFetch = now - lastFetchTimeRef.current;
    
    if (!forceRefresh && (isLoadingRef.current || timeSinceLastFetch < 1000)) {
      console.log('🛑 Preventing duplicate request, last fetch was', timeSinceLastFetch, 'ms ago');
      return;
    }

    // Cancel any ongoing requests
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Create new abort controller for this batch of requests
    abortControllerRef.current = new AbortController();
    
    isLoadingRef.current = true;
    lastFetchTimeRef.current = now;
    
    if (!mountedRef.current) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const days = getDaysFromPeriod(selectedPeriod);
      console.log(`🔄 Fetching dashboard data for ${days} days (force: ${forceRefresh})`);
      
      // Step 1: Check if we have a token (no need for separate API call)
      const token = localStorage.getItem('access_token');
      if (!token) {
        console.error('❌ No access token found');
        if (mountedRef.current) {
          setError('Authentication required. Please login again.');
        }
        return;
      }

      // Step 2: Try to fetch basic user data first
      let analyticsData = null;
      try {
        console.log('📊 Fetching analytics data...');
        analyticsData = await fetchAPI(`/api/analytics/user?include_detailed=true&days=${days}`);
        if (!mountedRef.current) return;
        console.log('📊 Analytics data received:', analyticsData);
        
        if (analyticsData?.error) {
          console.warn('⚠️ Analytics returned error:', analyticsData.error_message);
        }
      } catch (error) {
        if (!mountedRef.current) return;
        console.error('❌ Analytics fetch failed:', error);
        displayNotification('Failed to load analytics data: ' + error.message, 'error');
      }

      // Step 3: Fetch supporting data in parallel with proper error handling
      const dataPromises = {
        dailyStats: fetchAPI(`/api/analytics/daily-stats?days=${days}`)
          .then(data => ({ success: true, data }))
          .catch(error => ({ success: false, error: error?.message || 'Unknown error' })),
        
        performance: fetchAPI(`/api/analytics/performance?limit=10&time_range=${days}`)
          .then(data => ({ success: true, data }))
          .catch(error => ({ success: false, error: error?.message || 'Unknown error' })),
        
        campaigns: fetchAPI('/api/campaigns?limit=10')
          .then(data => ({ success: true, data }))
          .catch(error => ({ success: false, error: error?.message || 'Unknown error' })),
        
        users: fetchAPI('/api/admin/users?page=1&per_page=10')
          .then(data => ({ success: true, data }))
          .catch(error => ({ success: false, error: error?.message || 'Unknown error' })),
        
        revenue: fetchAPI(`/api/analytics/revenue?days=${days}`)
          .then(data => ({ success: true, data }))
          .catch(error => ({ success: false, error: error?.message || 'Unknown error' })),
        
        metrics: fetchAPI('/api/admin/metrics')
          .then(data => ({ success: true, data }))
          .catch(error => ({ success: false, error: error?.message || 'Unknown error' }))
      };

      const results = await Promise.allSettled(Object.values(dataPromises));
      if (!mountedRef.current) return;
      
      const dataMap = {};
      
      Object.keys(dataPromises).forEach((key, index) => {
        const result = results[index];
        if (result.status === 'fulfilled' && result.value?.success) {
          dataMap[key] = result.value.data;
          console.log(`✅ ${key} data loaded:`, result.value.data);
        } else {
          console.warn(`⚠️ ${key} fetch failed:`, result.reason || result.value?.error);
          dataMap[key] = null;
        }
      });

      // BATCH STATE UPDATES to prevent multiple re-renders
      const updates = {};

      // Step 4: Process analytics data or set defaults
      if (analyticsData && !analyticsData.error) {
        const pricePerSubmission = dataMap.revenue?.price_per_submission || 0.5;
        const totalRevenue = dataMap.revenue?.total_revenue || 
                            ((analyticsData.successful_submissions || 0) * pricePerSubmission);
        
        const processedStats = [
          { 
            label: "Total Revenue", 
            value: `$${totalRevenue.toFixed(2)}`,
            change: dataMap.revenue?.revenue_change || "N/A",
            isPositive: dataMap.revenue?.revenue_change?.startsWith('+') || null,
            icon: DollarSign,
            description: "From successful submissions"
          },
          { 
            label: "Active Campaigns", 
            value: String(analyticsData.active_campaigns || 0),
            change: analyticsData.campaigns_count > 0 ? 
                   `${((analyticsData.active_campaigns / analyticsData.campaigns_count) * 100).toFixed(1)}%` : 
                   "0%",
            isPositive: true,
            icon: Users,
            description: `Out of ${analyticsData.campaigns_count} total`
          },
          { 
            label: "Total Submissions", 
            value: String(analyticsData.total_submissions || 0),
            change: dataMap.dailyStats?.summary?.change_from_previous || "N/A",
            isPositive: dataMap.dailyStats?.summary?.change_from_previous?.startsWith('+') || null,
            icon: UserPlus,
            description: "All time"
          },
          { 
            label: "Success Rate", 
            value: `${(analyticsData.success_rate || 0).toFixed(1)}%`,
            change: dataMap.revenue?.success_rate_change || "N/A",
            isPositive: dataMap.revenue?.success_rate_change?.startsWith('+') || null,
            icon: Target,
            description: `${analyticsData.successful_submissions} successful out of ${analyticsData.total_submissions}`
          }
        ];
        updates.stats = processedStats;

        // Set system metrics
        if (dataMap.metrics) {
          updates.systemMetrics = {
            totalCampaigns: dataMap.metrics.campaigns?.total || analyticsData.campaigns_count || 0,
            activeCSVs: dataMap.metrics.campaigns?.active || analyticsData.active_campaigns || 0,
            avgSuccessRate: dataMap.metrics.submissions?.success_rate || analyticsData.success_rate || 0,
            totalSubmissions: formatNumber(dataMap.metrics.submissions?.total || analyticsData.total_submissions || 0),
            serverLoad: dataMap.metrics.system?.query_time_ms ? 
                       Math.min(100, Math.round(dataMap.metrics.system.query_time_ms / 10)) : 0
          };
        } else {
          updates.systemMetrics = {
            totalCampaigns: analyticsData.campaigns_count || 0,
            activeCSVs: analyticsData.active_campaigns || 0,
            avgSuccessRate: analyticsData.success_rate || 0,
            totalSubmissions: formatNumber(analyticsData.total_submissions || 0),
            serverLoad: 0
          };
        }
      } else {
        console.warn('⚠️ No analytics data available, setting defaults');
        // Set default empty stats
        const defaultStats = [
          { label: "Total Revenue", value: "$0.00", change: "N/A", icon: DollarSign, description: "No data available" },
          { label: "Active Campaigns", value: "0", change: "N/A", icon: Users, description: "No campaigns found" },
          { label: "Total Submissions", value: "0", change: "N/A", icon: UserPlus, description: "No submissions yet" },
          { label: "Success Rate", value: "0%", change: "N/A", icon: Target, description: "No data to calculate" }
        ];
        updates.stats = defaultStats;
        
        updates.systemMetrics = {
          totalCampaigns: 0,
          activeCSVs: 0,
          avgSuccessRate: 0,
          totalSubmissions: "0",
          serverLoad: 0
        };
      }

      // Process daily stats for charts
      if (dataMap.dailyStats?.series?.length > 0) {
        const pricePerSubmission = dataMap.revenue?.price_per_submission || 0.5;
        const revenue = dataMap.dailyStats.series.map((day) => ({
          month: new Date(day.day).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
          revenue: (day.success || 0) * pricePerSubmission,
          submissions: day.total,
          successful: day.success
        }));
        updates.revenueData = revenue;

        const activity = dataMap.dailyStats.series.map(day => ({
          hour: new Date(day.day).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
          submissions: day.total
        }));
        updates.customerActivity = activity;
      } else {
        updates.revenueData = [];
        updates.customerActivity = [];
      }

      // Process campaigns data
      if (dataMap.performance?.campaigns?.length > 0) {
        const pricePerSubmission = dataMap.revenue?.price_per_submission || 0.5;
        const transactions = dataMap.performance.campaigns.slice(0, 5).map((campaign) => ({
          id: campaign.id,
          customer: campaign.name || "Unnamed Campaign",
          status: campaign.status || 'UNKNOWN',
          amount: `$${((campaign.successful || 0) * pricePerSubmission).toFixed(2)}`,
          date: campaign.created_at ? new Date(campaign.created_at).toLocaleDateString() : 'N/A',
          urls: campaign.total_urls || 0
        }));
        updates.recentTransactions = transactions;
        updates.campaigns = dataMap.performance.campaigns;
      } else if (dataMap.campaigns && Array.isArray(dataMap.campaigns)) {
        const pricePerSubmission = dataMap.revenue?.price_per_submission || 0.5;
        const transactions = dataMap.campaigns.slice(0, 5).map((campaign) => ({
          id: campaign.id,
          customer: campaign.name || "Unnamed Campaign",
          status: campaign.status || 'UNKNOWN',
          amount: `$${((campaign.successful || 0) * pricePerSubmission).toFixed(2)}`,
          date: campaign.created_at ? new Date(campaign.created_at).toLocaleDateString() : 'N/A',
          urls: campaign.total_urls || 0
        }));
        updates.recentTransactions = transactions;
        updates.campaigns = dataMap.campaigns;
      } else {
        updates.recentTransactions = [];
        updates.campaigns = [];
      }

      // Process team members
      if (dataMap.users?.users?.length > 0) {
        const pricePerSubmission = dataMap.revenue?.price_per_submission || 0.5;
        const processedTeamMembers = dataMap.users.users.map(user => ({
          id: user.id,
          name: `${user.first_name || ''} ${user.last_name || ''}`.trim() || 'Unknown User',
          email: user.email,
          role: user.role || 'user',
          status: user.is_active ? 'Active' : 'Inactive',
          isVerified: user.is_verified || false,
          lastActive: user.stats?.last_activity || user.updated_at || null,
          campaigns: user.stats?.campaigns || 0,
          submissions: user.stats?.submissions || 0,
          revenue: `$${((user.stats?.successful_submissions || 0) * pricePerSubmission).toFixed(2)}`,
          performance: 0,
          createdAt: user.created_at
        }));
        updates.teamMembers = processedTeamMembers;
      } else {
        updates.teamMembers = [];
      }

      // BATCH UPDATE ALL STATE AT ONCE
      if (mountedRef.current) {
        setStats(updates.stats || []);
        setSystemMetrics(updates.systemMetrics || {});
        setRevenueData(updates.revenueData || []);
        setCustomerActivity(updates.customerActivity || []);
        setRecentTransactions(updates.recentTransactions || []);
        setCampaigns(updates.campaigns || []);
        setTeamMembers(updates.teamMembers || []);
      }

      console.log('✅ Dashboard data loading completed');
      
    } catch (err) {
      console.error('❌ Dashboard data loading failed:', err);
      if (mountedRef.current) {
        setError(`Failed to load dashboard data: ${err.message}`);
        displayNotification('Failed to load dashboard data. Please try again.', 'error');
      }
    } finally {
      isLoadingRef.current = false;
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, [selectedPeriod, getDaysFromPeriod, fetchAPI, displayNotification]);

  // OPTIMIZED useEffect - only fetch when necessary
  useEffect(() => {
    // Debug authentication state
    const token = localStorage.getItem('access_token');
    const userInfo = localStorage.getItem('user_info');
    
    console.log('🔍 Auth Debug:', {
      hasToken: !!token,
      tokenLength: token?.length,
      tokenPreview: token?.substring(0, 20) + '...',
      hasUserInfo: !!userInfo,
      userInfo: userInfo ? JSON.parse(userInfo) : null,
      apiBaseUrl: API_BASE_URL
    });
    
    if (!token) {
      console.error('❌ No access token found - user needs to login');
      setError('Please login to view dashboard');
      setLoading(false);
      return;
    }
    
    fetchDashboardData();
  }, [selectedPeriod, fetchDashboardData]);

  // FIXED: Manual refresh function
  const handleRefresh = useCallback(() => {
    fetchDashboardData(true); // Force refresh
  }, [fetchDashboardData]);

  const formatNumber = (num) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return String(num);
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'No activity';
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} mins ago`;
    if (diffHours < 24) return `${diffHours} hours ago`;
    if (diffDays < 7) return `${diffDays} days ago`;
    return date.toLocaleDateString();
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-100 flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-12 h-12 animate-spin text-slate-600 mx-auto mb-4" />
          <p className="text-slate-600">Loading dashboard data...</p>
          <p className="text-slate-400 text-sm mt-2">API: {API_BASE_URL}</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-100 flex items-center justify-center">
        <div className="text-center bg-white rounded-lg shadow-sm border border-slate-200 p-8 max-w-md">
          <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-slate-800 mb-2">Error Loading Dashboard</h2>
          <p className="text-slate-600 mb-4">{error}</p>
          <button 
            onClick={handleRefresh}
            className="px-4 py-2 bg-slate-800 text-white rounded hover:bg-slate-700 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Get logged-in user's name from localStorage
  const userInfo = JSON.parse(localStorage.getItem('user_info') || '{}');
  const firstName = userInfo?.first_name || userInfo?.name?.split(' ')[0] || 'User';

  // Get subtitle based on selected period
  const getSubtitle = () => {
    switch(selectedPeriod) {
      case 'today': return "Here's what's happening with your business today";
      case 'week': return "Your business performance this week";
      case 'month': return "Your business overview this month";
      case 'year': return "Your business performance this year";
      default: return "Your business overview this month";
    }
  };

  return (
    <div className="min-h-screen bg-slate-100">
      {/* Professional Notification Toast */}
      {showNotification && (
        <div className="fixed top-4 right-4 z-50 min-w-[320px] max-w-md">
          <div className={`
            bg-white border-l-4 rounded shadow-lg p-4 transform transition-all duration-300 border border-slate-200
            ${showNotification ? 'translate-x-0 opacity-100' : 'translate-x-full opacity-0'}
            ${notificationType === 'success' ? 'border-l-green-600 bg-green-50' : 
              notificationType === 'error' ? 'border-l-red-600 bg-red-50' : 'border-l-blue-600 bg-blue-50'}
          `}>
            <div className="flex items-start">
              <div className={`
                flex-shrink-0 w-8 h-8 rounded flex items-center justify-center mr-3
                ${notificationType === 'success' ? 'bg-green-100' : 
                  notificationType === 'error' ? 'bg-red-100' : 'bg-blue-100'}
              `}>
                {notificationType === 'success' && <CheckCircle className="w-5 h-5 text-green-600" />}
                {notificationType === 'error' && <AlertCircle className="w-5 h-5 text-red-600" />}
              </div>
              <div className="flex-1">
                <p className={`font-semibold text-sm
                  ${notificationType === 'success' ? 'text-green-800' : 
                    notificationType === 'error' ? 'text-red-800' : 'text-blue-800'}
                `}>
                  {notificationType === 'success' ? 'Success' : 'Error'}
                </p>
                <p className={`text-sm mt-1
                  ${notificationType === 'success' ? 'text-green-700' : 
                    notificationType === 'error' ? 'text-red-700' : 'text-blue-700'}
                `}>
                  {notificationMessage}
                </p>
              </div>
              <button 
                onClick={() => setShowNotification(false)}
                className={`flex-shrink-0 ml-2 rounded p-1 hover:opacity-80 transition-opacity
                  ${notificationType === 'success' ? 'text-green-600' : 
                    notificationType === 'error' ? 'text-red-600' : 'text-blue-600'}
                `}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}
      
      <div className="max-w-7xl mx-auto px-4 py-8">
        {/* Dashboard Top Section */}
        <div className="bg-white rounded-2xl p-8 mb-6 text-slate-800 shadow-sm border border-slate-200">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Left Side - Welcome & Quick Actions */}
            <div>
              <div className="flex items-center space-x-3 mb-4">
                <div className="p-2 bg-slate-100 rounded-lg border border-slate-200">
                  <BarChart3 className="w-6 h-6 text-slate-700" />
                </div>
                <div>
                  <h1 className="text-2xl font-bold text-slate-800">
                    Welcome back, {firstName}!
                  </h1>
                  <p className="text-slate-600 text-sm">
                    {getSubtitle()}
                  </p>
                </div>
              </div>
              
              {/* Time Period Selector */}
              <div className="flex items-center space-x-3 mt-6">
                <span className="text-slate-600 text-sm font-medium">Viewing:</span>
                <div className="flex bg-slate-100 rounded-lg p-1 border border-slate-200">
                  {['today', 'week', 'month', 'year'].map((period) => (
                    <button
                      key={period}
                      onClick={() => setSelectedPeriod(period)}
                      disabled={loading}
                      className={`px-3 py-1 rounded text-sm font-medium transition-all ${
                        selectedPeriod === period 
                          ? 'bg-slate-800 text-white shadow-sm' 
                          : 'text-slate-600 hover:bg-slate-200'
                      } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {period === 'today' ? 'Today' : 
                       period === 'week' ? 'This Week' : 
                       period === 'month' ? 'This Month' : 'This Year'}
                    </button>
                  ))}
                </div>
                <button 
                  onClick={handleRefresh}
                  disabled={loading}
                  className={`p-2 bg-slate-100 border border-slate-200 rounded-lg hover:bg-slate-200 transition-colors ${
                    loading ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                  title="Refresh data"
                >
                  <RefreshCw className={`w-4 h-4 text-slate-600 ${loading ? 'animate-spin' : ''}`} />
                </button>
              </div>
            </div>
            
            {/* Right Side - Quick Stats */}
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="flex items-center justify-between mb-2">
                  <DollarSign className="w-5 h-5 text-slate-600" />
                  <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded font-medium">
                    {stats[0]?.change !== "N/A" ? stats[0]?.change : "+0%"}
                  </span>
                </div>
                <p className="text-2xl font-bold text-slate-800">{stats[0]?.value || "$0.00"}</p>
                <p className="text-slate-600 text-xs mt-1 font-medium">Total Revenue</p>
              </div>
              
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="flex items-center justify-between mb-2">
                  <Activity className="w-5 h-5 text-slate-600" />
                  <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded font-medium">
                    Active
                  </span>
                </div>
                <p className="text-2xl font-bold text-slate-800">{systemMetrics.activeCSVs}</p>
                <p className="text-slate-600 text-xs mt-1 font-medium">Running Campaigns</p>
              </div>
              
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="flex items-center justify-between mb-2">
                  <Target className="w-5 h-5 text-slate-600" />
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                    systemMetrics.avgSuccessRate > 50 
                      ? 'bg-green-100 text-green-700' 
                      : systemMetrics.avgSuccessRate > 0 
                      ? 'bg-yellow-100 text-yellow-700'
                      : 'bg-gray-100 text-gray-700'
                  }`}>
                    {systemMetrics.avgSuccessRate > 50 ? 'Good' : 
                     systemMetrics.avgSuccessRate > 0 ? 'Needs Work' : 'No Data'}
                  </span>
                </div>
                <p className="text-2xl font-bold text-slate-800">{systemMetrics.avgSuccessRate.toFixed(1)}%</p>
                <p className="text-slate-600 text-xs mt-1 font-medium">Success Rate</p>
              </div>
              
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="flex items-center justify-between mb-2">
                  <Users className="w-5 h-5 text-slate-600" />
                  <span className="text-xs bg-slate-200 text-slate-700 px-2 py-0.5 rounded font-medium">
                    Team
                  </span>
                </div>
                <p className="text-2xl font-bold text-slate-800">{teamMembers.length}</p>
                <p className="text-slate-600 text-xs mt-1 font-medium">Active Users</p>
              </div>
            </div>
          </div>
        </div>

        {/* System Health Bar */}
        <div className={`rounded-lg p-4 mb-6 text-white flex items-center justify-between border ${
          systemMetrics.avgSuccessRate > 50 ? 'bg-green-600 border-green-700' : 
          systemMetrics.avgSuccessRate > 0 ? 'bg-yellow-600 border-yellow-700' :
          'bg-slate-600 border-slate-700'
        }`}>
          <div className="flex items-center space-x-3">
            <div className="w-3 h-3 bg-white rounded-full animate-pulse"></div>
            <span className="font-semibold">
              System Status: {systemMetrics.avgSuccessRate > 50 ? 'All Services Operational' : 
                              systemMetrics.avgSuccessRate > 0 ? 'Performance Issues Detected' :
                              'No Data Available'}
            </span>
          </div>
          <div className="flex items-center space-x-6 text-sm">
            <div className="flex items-center space-x-2">
              <Activity className="w-4 h-4" />
              <span>Load: {systemMetrics.serverLoad || '0'}%</span>
            </div>
            <div className="flex items-center space-x-2">
              <FileText className="w-4 h-4" />
              <span>{systemMetrics.activeCSVs} Active Campaigns</span>
            </div>
            <div className="flex items-center space-x-2">
              <Target className="w-4 h-4" />
              <span>{systemMetrics.avgSuccessRate.toFixed(1)}% Success</span>
            </div>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {stats.map((stat, idx) => {
            const Icon = stat.icon;
            const borderColors = ['border-green-500', 'border-blue-500', 'border-purple-500', 'border-orange-500'];
            const iconColors = ['bg-green-50 text-green-600', 'bg-blue-50 text-blue-600', 'bg-purple-50 text-purple-600', 'bg-orange-50 text-orange-600'];
            const changeColors = ['text-green-600', 'text-blue-600', 'text-purple-600', 'text-orange-600'];
            
            return (
              <div key={idx} className={`bg-white rounded-lg shadow-sm border-l-4 ${borderColors[idx]} p-6 hover:shadow-md transition-all`}>
                <div className="flex items-center justify-between mb-2">
                  <div className={`${iconColors[idx]} p-3 rounded`}>
                    <Icon className="w-5 h-5" />
                  </div>
                  {stat.change !== "N/A" && (
                    <span className={`text-xs font-semibold flex items-center ${
                      stat.isPositive ? changeColors[idx] : stat.isPositive === false ? 'text-red-600' : 'text-slate-600'
                    }`}>
                      {stat.isPositive !== null && (
                        <TrendingUp className={`w-3 h-3 mr-1 ${!stat.isPositive && 'rotate-180'}`} />
                      )}
                      {stat.change}
                    </span>
                  )}
                </div>
                <p className="text-2xl font-bold text-slate-800">{stat.value}</p>
                <p className="text-sm text-slate-600 font-medium">{stat.label}</p>
                <p className="text-xs text-slate-500 mt-1">{stat.description}</p>
              </div>
            );
          })}
        </div>

        {/* Recent Campaigns */}
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-6">
          <h3 className="text-lg font-semibold text-slate-800 mb-4 flex items-center">
            <CreditCard className="w-5 h-5 mr-2 text-slate-600" />
            Recent Campaign Activity
          </h3>
          <div className="space-y-3">
            {recentTransactions.length > 0 ? (
              recentTransactions.map((transaction) => (
                <div key={transaction.id} className="flex items-center justify-between p-3 rounded border border-slate-200 hover:bg-slate-50 transition-colors">
                  <div className="flex items-center space-x-3">
                    <div className={`w-2 h-2 rounded-full ${
                      transaction.status === 'COMPLETED' || transaction.status === 'completed' ? 'bg-green-500' : 
                      transaction.status === 'FAILED' || transaction.status === 'failed' ? 'bg-red-500' :
                      transaction.status === 'PROCESSING' || transaction.status === 'ACTIVE' ? 'bg-yellow-500' :
                      'bg-slate-500'
                    }`}></div>
                    <div>
                      <p className="text-sm font-medium text-slate-800">{transaction.customer}</p>
                      <p className="text-xs text-slate-500 font-medium">{transaction.urls} URLs • {transaction.date}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-bold text-slate-800">{transaction.amount}</p>
                    <p className={`text-xs font-medium ${
                      transaction.status === 'COMPLETED' || transaction.status === 'completed' ? 'text-green-600' : 
                      transaction.status === 'FAILED' || transaction.status === 'failed' ? 'text-red-600' :
                      transaction.status === 'PROCESSING' || transaction.status === 'ACTIVE' ? 'text-yellow-600' :
                      'text-slate-600'
                    }`}>
                      {transaction.status}
                    </p>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-8">
                <FileText className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                <p className="text-sm text-slate-500">No recent campaign activity</p>
                <p className="text-xs text-slate-400 mt-1">Create a campaign to see activity here</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default OwnerDashboard;