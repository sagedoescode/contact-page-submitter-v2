// src/services/api.js - Complete API Service with Fixed WebSocket
import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

class ApiService {
  constructor() {
    this.axiosInstance = axios.create({
      baseURL: BASE_URL,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.setupInterceptors();
  }

  setupInterceptors() {
    // Request interceptor
    this.axiosInstance.interceptors.request.use(
      (config) => {
        const token = localStorage.getItem('access_token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Response interceptor
    this.axiosInstance.interceptors.response.use(
      (response) => response.data,
      (error) => {
        console.error('[API] Request failed:', error);
        
        if (error.response?.status === 401) {
          console.log('[API] Unauthorized, clearing tokens');
          localStorage.removeItem('access_token');
          localStorage.removeItem('user_info');
          window.location.href = '/';
        }
        
        return Promise.reject(error);
      }
    );
  }

  // Generic request method
  async makeRequest(method, url, data = null, config = {}) {
    try {
      console.log(`[API] ${method.toUpperCase()} ${url}`, data ? { data } : '');
      
      const response = await this.axiosInstance({
        method,
        url,
        data,
        ...config
      });
      
      console.log(`[API] ${method.toUpperCase()} ${url} - Success:`, response);
      return response;
    } catch (error) {
      console.error(`[API] ${method.toUpperCase()} ${url} - Error:`, error);
      
      if (error.response?.data) {
        throw new Error(error.response.data.detail || error.response.data.message || 'Request failed');
      }
      throw error;
    }
  }

  // ============= AUTH METHODS =============
  async login(email, password) {
    const response = await this.makeRequest('post', '/api/auth/login', { email, password });
    if (response && response.access_token) {
      localStorage.setItem('access_token', response.access_token);
      localStorage.setItem('user_info', JSON.stringify(response.user));
    }
    return response;
  }

  async register(userData) {
    const response = await this.makeRequest('post', '/api/auth/register', userData);
    if (response && response.access_token) {
      localStorage.setItem('access_token', response.access_token);
      localStorage.setItem('user_info', JSON.stringify(response.user));
    }
    return response;
  }

  async logout() {
    try {
      await this.makeRequest('post', '/api/auth/logout');
    } finally {
      localStorage.removeItem('access_token');
      localStorage.removeItem('user_info');
    }
  }

  async getCurrentUser() {
    return this.makeRequest('get', '/api/auth/me');
  }

  // ============= CAMPAIGNS =============
  async getCampaigns(params = {}) {
    try {
      const response = await this.makeRequest('get', '/api/campaigns', null, { params });
      return Array.isArray(response) ? response : (response?.data || []);
    } catch (error) {
      console.error('[API] Error loading campaigns:', error);
      return [];
    }
  }

  async getCampaign(campaignId) {
    return this.makeRequest('get', `/api/campaigns/${campaignId}`);
  }

  async createCampaign(data) {
    return this.makeRequest('post', '/api/campaigns', data);
  }

  async updateCampaign(campaignId, data) {
    return this.makeRequest('put', `/api/campaigns/${campaignId}`, data);
  }

  async deleteCampaign(campaignId) {
    return this.makeRequest('delete', `/api/campaigns/${campaignId}`);
  }

  async startCampaign(campaignId) {
    return this.makeRequest('post', `/api/campaigns/${campaignId}/start`);
  }

  async pauseCampaign(campaignId) {
    return this.makeRequest('post', `/api/campaigns/${campaignId}/pause`);
  }

  async stopCampaign(campaignId) {
    return this.makeRequest('post', `/api/campaigns/${campaignId}/stop`);
  }

  async getCampaignStatus(campaignId) {
    return this.makeRequest('get', `/api/campaigns/${campaignId}/status`);
  }

  async startCampaignWithCSV(file, campaignData) {
    const formData = new FormData();
    formData.append('file', file);
    
    // Add other campaign data
    formData.append('name', campaignData.name || '');
    formData.append('message', campaignData.message || '');
    formData.append('proxy', campaignData.proxy || '');
    formData.append('use_captcha', campaignData.use_captcha || false);
    
    if (campaignData.settings) {
      formData.append('settings', JSON.stringify(campaignData.settings));
    }

    return this.makeRequest('post', '/api/campaigns/start', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
  }

  // ============= ANALYTICS =============
  async getUserAnalytics() {
    try {
      const response = await this.makeRequest('get', '/api/analytics/user');
      return {
        campaigns_count: response.campaigns_count || 0,
        total_campaigns: response.campaigns_count || 0,
        active_campaigns: response.active_campaigns || 0,
        completed_campaigns: response.completed_campaigns || 0,
        success_rate: response.success_rate || 0,
        total_submissions: response.total_submissions || 0,
        successful_submissions: response.successful_submissions || 0,
        failed_submissions: response.failed_submissions || 0,
        websites_count: response.websites_count || 0,
        ...response
      };
    } catch (error) {
      console.warn('[API] Analytics endpoint failed:', error);
      return {
        campaigns_count: 0,
        total_campaigns: 0,
        active_campaigns: 0,
        completed_campaigns: 0,
        success_rate: 0,
        total_submissions: 0,
        successful_submissions: 0,
        failed_submissions: 0,
        websites_count: 0,
        error: true
      };
    }
  }

  async getPerformanceMetrics(days = 30) {
    try {
      const response = await this.makeRequest('get', '/api/analytics/performance', null, {
        params: { time_range: days }
      });
      return response;
    } catch (error) {
      console.warn('[API] Performance metrics endpoint failed:', error);
      return {
        success_rate: 0,
        processing_speed: 0,
        average_duration: 0
      };
    }
  }

  // ============= WEBSOCKET - FIXED =============
  connectWebSocket(onMessage, onError, onClose, campaignId = null) {
    // Build WebSocket URL - connect to /api/ws
    const wsBase = BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://');
    const wsPath = campaignId ? `/api/ws/campaign/${campaignId}` : '/api/ws';
    const wsUrl = `${wsBase}${wsPath}`;
    const token = localStorage.getItem('access_token');
    
    if (!token) {
      console.error('[WS] No authentication token found');
      if (onError) onError(new Error('No authentication token'));
      return null;
    }
    
    try {
      console.log('[WS] Connecting to:', wsUrl);
      const ws = new WebSocket(`${wsUrl}?token=${token}`);
      
      ws.onopen = () => {
        console.log('[WS] WebSocket connected successfully');
        
        // Send initial ping to verify connection
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('[WS] Message received:', data);
          
          // Handle different message types
          if (data.type === 'connection') {
            console.log('[WS] Connection confirmed:', data.message);
          } else if (data.type === 'pong') {
            console.log('[WS] Pong received');
          } else if (data.type === 'keepalive') {
            console.log('[WS] Keepalive received');
          } else if (data.type === 'campaign_update') {
            console.log('[WS] Campaign update:', data);
            if (onMessage) onMessage(data);
          } else {
            if (onMessage) onMessage(data);
          }
        } catch (error) {
          console.error('[WS] Failed to parse message:', error);
          console.log('[WS] Raw message:', event.data);
        }
      };
      
      ws.onerror = (error) => {
        console.error('[WS] WebSocket error:', error);
        if (onError) onError(error);
      };
      
      ws.onclose = (event) => {
        console.log('[WS] WebSocket closed:', {
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean
        });
        if (onClose) onClose(event);
      };
      
      // Set up ping interval to keep connection alive
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        } else {
          clearInterval(pingInterval);
        }
      }, 30000); // Ping every 30 seconds
      
      // Store interval ID for cleanup
      ws._pingInterval = pingInterval;
      
      return ws;
    } catch (error) {
      console.error('[WS] WebSocket connection failed:', error);
      if (onError) onError(error);
      return null;
    }
  }
  
  // Helper to close WebSocket properly
  closeWebSocket(ws) {
    if (ws) {
      if (ws._pingInterval) {
        clearInterval(ws._pingInterval);
      }
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    }
  }

  // ============= BATCH OPERATIONS =============
  async batchDeleteCampaigns(campaignIds) {
    const results = await Promise.allSettled(
      campaignIds.map(id => this.deleteCampaign(id))
    );
    const successful = results.filter(r => r.status === 'fulfilled').length;
    return { deleted: successful, total: campaignIds.length };
  }

  // ============= UTILITY =============
  debugHeaders() {
    const token = localStorage.getItem('access_token');
    return {
      hasToken: !!token,
      tokenLength: token?.length,
      baseURL: BASE_URL,
      timestamp: new Date().toISOString()
    };
  }
}

// Create singleton instance
const apiService = new ApiService();

export default apiService;
export { ApiService, BASE_URL };