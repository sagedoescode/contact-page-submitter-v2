// ============================================================================
// FILE 3: src/utils/validators.js - Form Validators
// ============================================================================

/**
 * Validation utilities for campaign forms
 */

export const validators = {
  // Validate CSV file
  validateCSVFile: (file) => {
    const errors = [];

    if (!file) {
      errors.push('CSV file is required');
      return errors;
    }

    if (!file.name.toLowerCase().endsWith('.csv')) {
      errors.push('File must be a CSV file');
    }

    const maxSize = 5 * 1024 * 1024; // 5MB
    if (file.size > maxSize) {
      errors.push('File size must be less than 5MB');
    }

    if (file.size === 0) {
      errors.push('CSV file is empty');
    }

    return errors;
  },

  // Validate campaign name
  validateCampaignName: (name) => {
    const errors = [];

    if (!name || name.trim().length === 0) {
      errors.push('Campaign name is required');
    } else if (name.trim().length < 3) {
      errors.push('Campaign name must be at least 3 characters');
    } else if (name.trim().length > 100) {
      errors.push('Campaign name must be less than 100 characters');
    }

    return errors;
  },

  // Validate message
  validateMessage: (message) => {
    const errors = [];

    if (!message || message.trim().length === 0) {
      errors.push('Message is required');
    } else if (message.trim().length < 10) {
      errors.push('Message must be at least 10 characters');
    } else if (message.trim().length > 1000) {
      errors.push('Message must be less than 1000 characters');
    }

    return errors;
  },

  // Validate user profile
  validateUserProfile: (profile) => {
    const errors = [];

    if (!profile.first_name || profile.first_name.trim().length === 0) {
      errors.push('First name is required');
    }

    if (!profile.last_name || profile.last_name.trim().length === 0) {
      errors.push('Last name is required');
    }

    if (!profile.email || profile.email.trim().length === 0) {
      errors.push('Email is required');
    } else if (!isValidEmail(profile.email)) {
      errors.push('Email format is invalid');
    }

    if (!profile.message || profile.message.trim().length === 0) {
      errors.push('Message template is required');
    }

    return errors;
  },

  // Validate email format
  validateEmail: (email) => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  },
};

export const isValidEmail = (email) => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

/**
 * Parse CSV content and extract URLs
 */
export const parseCSVContent = (csvText) => {
  const lines = csvText.split('\n');
  const urls = [];
  const errors = [];

  lines.forEach((line, index) => {
    const trimmed = line.trim();

    // Skip empty lines and headers
    if (!trimmed || trimmed.toLowerCase() === 'url' || trimmed.toLowerCase() === 'website') {
      return;
    }

    // Try to parse as URL
    try {
      const url = new URL(trimmed);
      urls.push(url.href);
    } catch (err) {
      errors.push(`Line ${index + 1}: Invalid URL - ${trimmed}`);
    }
  });

  return { urls, errors };
};

/**
 * Format file size for display
 */
export const formatFileSize = (bytes) => {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
};

/**
 * Format date for display
 */
export const formatDate = (dateString) => {
  const date = new Date(dateString);
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
};

/**
 * Calculate time remaining
 */
export const calculateTimeRemaining = (processed, total, startTime) => {
  if (processed === 0) return 'Calculating...';

  const elapsed = Date.now() - startTime;
  const processedPerMs = processed / elapsed;
  const remaining = (total - processed) / processedPerMs;

  const seconds = Math.floor((remaining / 1000) % 60);
  const minutes = Math.floor((remaining / (1000 * 60)) % 60);
  const hours = Math.floor((remaining / (1000 * 60 * 60)) % 24);

  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
};
