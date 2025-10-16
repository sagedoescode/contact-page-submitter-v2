// src/hooks/useAuth.jsx - Fixed Error Handling
import React, { createContext, useContext, useState, useEffect } from "react";
import apiService from "../services/api";

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loginLoading, setLoginLoading] = useState(false);

  useEffect(() => {
    checkAuthStatus();
  }, []);

  const checkAuthStatus = async () => {
    console.log("[AUTH] Checking authentication status...");
    
    try {
      const token = localStorage.getItem("access_token");
      if (!token) {
        console.log("[AUTH] No token found");
        setLoading(false);
        return;
      }

      console.log("[AUTH] Token found, verifying with backend...");
      const response = await apiService.getCurrentUser();
      console.log("[AUTH] User verified:", response);
      setUser(response);
    } catch (error) {
      console.error("[AUTH] Token verification failed:", error);
      localStorage.removeItem("access_token");
      localStorage.removeItem("user_id");
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const login = async (email, password) => {
    console.log("[LOGIN] Attempting login for:", email);
    setLoginLoading(true);

    try {
      const response = await apiService.login(
        email.trim().toLowerCase(),
        password
      );

      console.log("[LOGIN] Login response:", response);

      if (response.access_token && response.user) {
        // Store token immediately
        localStorage.setItem("access_token", response.access_token);
        if (response.user?.id) {
          localStorage.setItem("user_id", response.user.id);
        }
        
        setUser(response.user);
        console.log("[LOGIN] Success - User logged in:", response.user);
        return { success: true, user: response.user };
      }

      return { success: false, error: "Invalid response from server" };
    } catch (error) {
      console.error("[LOGIN] Error:", error);

      // FIXED: Use the new error message helper
      const errorMessage = getErrorMessage(error, 'login');
      
      return { success: false, error: errorMessage };
    } finally {
      setLoginLoading(false);
    }
  };

  const register = async (userData) => {
    console.log("[REGISTER] Attempting registration for:", userData.email);
    setLoginLoading(true);

    try {
      const response = await apiService.register({
        ...userData,
        email: userData.email.trim().toLowerCase(),
      });

      console.log("[REGISTER] Registration response:", response);

      if (response.access_token && response.user) {
        // Store token immediately
        localStorage.setItem("access_token", response.access_token);
        if (response.user?.id) {
          localStorage.setItem("user_id", response.user.id);
        }
        
        setUser(response.user);
        console.log("[REGISTER] Success - User registered and logged in");
        return { success: true, user: response.user };
      }

      return { success: false, error: "Registration failed" };
    } catch (error) {
      console.error("[REGISTER] Error:", error);

      // FIXED: Use the new error message helper
      const errorMessage = getErrorMessage(error, 'register');
      
      return { success: false, error: errorMessage };
    } finally {
      setLoginLoading(false);
    }
  };

  const logout = async () => {
    console.log("[LOGOUT] Logging out user");
    try {
      await apiService.logout();
    } catch (error) {
      console.error("[LOGOUT] Error:", error);
    } finally {
      localStorage.removeItem("access_token");
      localStorage.removeItem("user_id");
      localStorage.clear();
      setUser(null);
      window.location.href = "/";
    }
  };

  const updateUser = (userData) => {
    setUser(prevUser => ({
      ...prevUser,
      ...userData
    }));
  };

  const refreshUser = async () => {
    try {
      const response = await apiService.getCurrentUser();
      setUser(response);
      return response;
    } catch (error) {
      console.error("[AUTH] Failed to refresh user:", error);
      return null;
    }
  };

  const value = {
    user,
    loading,
    loginLoading,
    login,
    register,
    logout,
    checkAuthStatus,
    updateUser,
    refreshUser,
    isAuthenticated: !!user,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

// FIXED: Centralized error message handling
const getErrorMessage = (error, action = 'operation') => {
  // Handle network errors first
  if (error.code === "ERR_NETWORK" || error.code === "ECONNABORTED") {
    return "Cannot connect to server. Please ensure the backend is running on http://127.0.0.1:8000";
  }

  // Handle HTTP response errors
  if (error.response) {
    const { status, data } = error.response;
    
    switch (status) {
      case 401:
        return "Invalid email or password. Please check your credentials.";
        
      case 403:
        const detail = data?.detail;
        if (typeof detail === 'string') {
          if (detail.includes("verify")) {
            return "Please verify your email to login.";
          } else if (detail.includes("inactive")) {
            return "Your account is inactive. Please contact support.";
          } else {
            return detail;
          }
        }
        return "Your account is restricted.";
        
      case 404:
        return `${action.charAt(0).toUpperCase() + action.slice(1)} service not found. Please check the server configuration.`;
        
      case 409:
        return "This email is already registered. Please login instead.";
        
      case 422:
        // Handle validation errors properly
        const validationErrors = data?.detail;
        if (Array.isArray(validationErrors)) {
          return validationErrors
            .map(err => {
              let field = 'Field';
              if (err.loc && Array.isArray(err.loc) && err.loc.length > 0) {
                field = err.loc[err.loc.length - 1];
                // Make field names more user-friendly
                if (field === 'email') field = 'Email';
                if (field === 'password') field = 'Password';
                if (field === 'first_name') field = 'First Name';
                if (field === 'last_name') field = 'Last Name';
              }
              return `${field}: ${err.msg || 'Invalid value'}`;
            })
            .join(", ");
        } else if (typeof validationErrors === 'string') {
          return validationErrors;
        } else {
          return `Invalid input. Please check your ${action === 'login' ? 'email and password' : 'information'}.`;
        }
        
      case 500:
        return "Server error. Please try again in a moment.";
        
      default:
        return data?.detail || data?.message || `${action.charAt(0).toUpperCase() + action.slice(1)} failed. Please try again.`;
    }
  }

  // Handle other error types
  if (error.message) {
    return error.message;
  }

  return `${action.charAt(0).toUpperCase() + action.slice(1)} failed. Please try again.`;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};

// Default export for backward compatibility
export default useAuth;