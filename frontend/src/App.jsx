// src/App.jsx - Fixed Version with Correct Owner Dashboard Import
import React, { useState, useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "react-hot-toast";
import useAuth from "./hooks/useAuth";
import AuthModal from "./components/AuthModal";
import AppLayout from "./components/layout/AppLayout";

// Import all pages - FIXED IMPORT PATHS
import UserDashboard from "./pages/UserDashboard";
import AdminDashboard from "./pages/AdminDashboard";
import OwnerDashboard from "./pages/OwnerDashboard"; // CORRECTED: Using pages folder
import ContactInformationForm from "./pages/ContactInformationForm";
import CampaignDetailPage from "./pages/CampaignDetailPage";
import ActivityPage from "./pages/ActivityPage";
import LandingPage from "./pages/LandingPage";
import DashboardPage from "./pages/DashboardPage";
import CampaignsPage from "./pages/CampaignsPage";
import FormSubmitterPage from "./pages/FormSubmitterPage";
import UserManagementPage from "./pages/UserManagementPage";
import ReportsPage from "./pages/ReportsPage";
import BillingPage from "./pages/BillingPage";
import MonitoringPage from "./pages/MonitoringPage";
import IntegrationsPage from "./pages/IntegrationsPage";
import NotificationsPage from "./pages/NotificationsPage";
import HelpSupportPage from "./pages/HelpSupportPage";
import SettingsPage from "./pages/SettingsPage";

// Enhanced Loading Component
const LoadingScreen = () => (
  <div className="flex items-center justify-center h-screen bg-gradient-to-br from-indigo-50 via-purple-50 to-pink-50">
    <div className="text-center">
      <div className="relative">
        <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-indigo-600 mx-auto"></div>
        <div className="absolute inset-0 animate-pulse rounded-full h-16 w-16 border-t-2 border-purple-600 mx-auto"></div>
      </div>
      <p className="mt-4 text-gray-600 font-medium">Loading your dashboard...</p>
      <p className="text-sm text-gray-500 mt-2">Preparing automation tools...</p>
    </div>
  </div>
);

// Enhanced Protected Route Component
const ProtectedRoute = ({ children, allowedRoles = [], requiresContactInfo = false }) => {
  const { user } = useAuth();
  const location = useLocation();

  if (!user) {
    sessionStorage.setItem('redirectAfterLogin', location.pathname);
    return <Navigate to="/" replace />;
  }

  // Check role permissions
  if (allowedRoles.length > 0 && !allowedRoles.includes(user.role)) {
    // Redirect to appropriate dashboard based on role
    const defaultPath = getDefaultPathForRole(user.role);
    return <Navigate to={defaultPath} replace />;
  }

  // Check if contact info is required and filled
  if (requiresContactInfo && (!user.contactInfoCompleted)) {
    if (location.pathname !== '/contact-info') {
      sessionStorage.setItem('redirectAfterContactInfo', location.pathname);
      return <Navigate to="/contact-info" replace />;
    }
  }

  return children;
};

// Get default path based on user role
const getDefaultPathForRole = (role) => {
  switch (role) {
    case 'owner':
      return '/owner';
    case 'admin':
      return '/admin';
    case 'user':
    default:
      return '/dashboard';
  }
};

// Role-based Dashboard Router
const RoleDashboard = () => {
  const { user } = useAuth();
  
  switch (user?.role) {
    case 'owner':
      return <Navigate to="/owner" replace />;
    case 'admin':
      return <Navigate to="/admin" replace />;
    case 'user':
    default:
      return <DashboardPage />;
  }
};

// Placeholder components for missing pages
const PlaceholderPage = ({ title, description }) => (
  <div className="min-h-screen bg-gray-50 p-8">
    <div className="max-w-4xl mx-auto">
      <div className="bg-white rounded-lg shadow-sm border p-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900 mb-4">
            {title}
          </h1>
          <p className="text-gray-600 mb-6">{description}</p>
          <div className="bg-blue-50 rounded-lg p-6">
            <p className="text-blue-700 font-medium">This page is under development</p>
            <p className="text-blue-600 text-sm mt-2">Coming soon with advanced features!</p>
          </div>
        </div>
      </div>
    </div>
  </div>
);

const App = () => {
  const { user, loading, login, register } = useAuth();
  const [showModal, setShowModal] = useState(false);
  const [view, setView] = useState("login");
  const location = useLocation();

  // Auto-redirect based on role on initial login
  useEffect(() => {
    if (user && location.pathname === '/') {
      const defaultPath = getDefaultPathForRole(user.role);
      window.location.href = defaultPath;
    }
  }, [user, location.pathname]);

  // Check for redirect after login
  useEffect(() => {
    if (user && sessionStorage.getItem('redirectAfterLogin')) {
      const redirect = sessionStorage.getItem('redirectAfterLogin');
      sessionStorage.removeItem('redirectAfterLogin');
      window.location.href = redirect;
    }
  }, [user]);

  // Check for redirect after contact info completion
  useEffect(() => {
    if (user?.contactInfoCompleted && sessionStorage.getItem('redirectAfterContactInfo')) {
      const redirect = sessionStorage.getItem('redirectAfterContactInfo');
      sessionStorage.removeItem('redirectAfterContactInfo');
      window.location.href = redirect;
    }
  }, [user?.contactInfoCompleted]);

  if (loading) {
    return <LoadingScreen />;
  }

  const openModal = (type) => {
    setView(type);
    setShowModal(true);
  };

  const handleLogin = async (email, password) => {
    const result = await login(email, password);
    if (result.success) {
      setShowModal(false);
      const redirect = sessionStorage.getItem('redirectAfterLogin');
      if (redirect) {
        sessionStorage.removeItem('redirectAfterLogin');
        window.location.href = redirect;
      } else {
        // Redirect to role-appropriate dashboard
        const defaultPath = getDefaultPathForRole(result.user?.role);
        window.location.href = defaultPath;
      }
    }
    return result;
  };

  const handleRegister = async (userData) => {
    const result = await register(userData);
    if (result.success) {
      setShowModal(false);
      // New users start with regular dashboard
      window.location.href = '/dashboard';
    }
    return result;
  };

  return (
    <>
      {/* Enhanced Toast Notifications */}
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 6000,
          style: {
            padding: "16px",
            fontSize: "14px",
            maxWidth: "500px",
            background: "#ffffff",
            color: "#1f2937",
            border: "1px solid #e5e7eb",
            borderRadius: "12px",
            boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
          },
          success: {
            iconTheme: { primary: "#10b981", secondary: "#ffffff" },
            style: { background: "#f0fdf4", color: "#166534", border: "1px solid #86efac" },
            duration: 4000,
          },
          error: {
            iconTheme: { primary: "#ef4444", secondary: "#ffffff" },
            style: { background: "#fef2f2", color: "#991b1b", border: "1px solid #fca5a5" },
            duration: 8000,
          },
          loading: {
            style: { background: "#f3f4f6", color: "#374151" },
            duration: Infinity,
          },
        }}
      />

      <Routes>
        <Route element={<AppLayout />}>
          {/* Public Routes */}
          <Route
            index
            element={
              user ? (
                <Navigate to={getDefaultPathForRole(user.role)} replace />
              ) : (
                <LandingPage
                  onLogin={() => openModal("login")}
                  onRegister={() => openModal("register")}
                />
              )
            }
          />

          {/* OWNER ROUTES - FIXED */}
          <Route
            path="/owner"
            element={
              <ProtectedRoute allowedRoles={["owner"]}>
                <OwnerDashboard />
              </ProtectedRoute>
            }
          />

          <Route
            path="/user-management"
            element={
              <ProtectedRoute allowedRoles={["owner", "admin"]}>
                {UserManagementPage ? <UserManagementPage /> : 
                <PlaceholderPage 
                  title="User Management" 
                  description="Manage all users and their permissions" 
                />}
              </ProtectedRoute>
            }
          />

          <Route
            path="/reports"
            element={
              <ProtectedRoute allowedRoles={["owner", "admin"]}>
                {ReportsPage ? <ReportsPage /> : 
                <PlaceholderPage 
                  title="Reports & Analytics" 
                  description="Comprehensive system reports and analytics" 
                />}
              </ProtectedRoute>
            }
          />

          <Route
            path="/billing"
            element={
              <ProtectedRoute allowedRoles={["owner"]}>
                {BillingPage ? <BillingPage /> : 
                <PlaceholderPage 
                  title="Billing & Payments" 
                  description="Manage billing, subscriptions, and payments" 
                />}
              </ProtectedRoute>
            }
          />

          <Route
            path="/monitoring"
            element={
              <ProtectedRoute allowedRoles={["owner", "admin"]}>
                {MonitoringPage ? <MonitoringPage /> : 
                <PlaceholderPage 
                  title="System Monitoring" 
                  description="Monitor system performance and health" 
                />}
              </ProtectedRoute>
            }
          />

          <Route
            path="/integrations"
            element={
              <ProtectedRoute allowedRoles={["owner"]}>
                {IntegrationsPage ? <IntegrationsPage /> : 
                <PlaceholderPage 
                  title="API Integrations" 
                  description="Manage third-party integrations and APIs" 
                />}
              </ProtectedRoute>
            }
          />

          {/* ADMIN ROUTES */}
          <Route
            path="/admin"
            element={
              <ProtectedRoute allowedRoles={["admin", "owner"]}>
                {AdminDashboard ? <AdminDashboard /> : 
                <PlaceholderPage 
                  title="Admin Dashboard" 
                  description="Administrative overview and controls" 
                />}
              </ProtectedRoute>
            }
          />

          {/* USER ROUTES */}
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <RoleDashboard />
              </ProtectedRoute>
            }
          />

          <Route
            path="/user"
            element={
              <ProtectedRoute allowedRoles={["user"]}>
                {UserDashboard ? <UserDashboard /> : <DashboardPage />}
              </ProtectedRoute>
            }
          />

          {/* SHARED ROUTES */}
          <Route
            path="/campaigns"
            element={
              <ProtectedRoute>
                <CampaignsPage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/campaign-detail"
            element={
              <ProtectedRoute>
                <CampaignDetailPage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/campaigns/:campaignId"
            element={
              <ProtectedRoute>
                <CampaignDetailPage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/campaigns/:campaignId/results"
            element={
              <ProtectedRoute>
                <CampaignDetailPage showResultsView={true} />
              </ProtectedRoute>
            }
          />

          <Route
            path="/form-submitter"
            element={
              <ProtectedRoute>
                <FormSubmitterPage 
                  enableRealTimeProgress={true}
                  enableAdvancedValidation={true}
                  showPerformanceMetrics={true}
                />
              </ProtectedRoute>
            }
          />

          <Route
            path="/activity"
            element={
              <ProtectedRoute>
                <ActivityPage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/contact-info"
            element={
              <ProtectedRoute>
                <ContactInformationForm />
              </ProtectedRoute>
            }
          />

          <Route
            path="/notifications"
            element={
              <ProtectedRoute>
                {NotificationsPage ? <NotificationsPage /> : 
                <PlaceholderPage 
                  title="Notifications" 
                  description="Manage your notifications and alerts" 
                />}
              </ProtectedRoute>
            }
          />

          <Route
            path="/help"
            element={
              <ProtectedRoute>
                {HelpSupportPage ? <HelpSupportPage /> : 
                <PlaceholderPage 
                  title="Help & Support" 
                  description="Get help and support for the platform" 
                />}
              </ProtectedRoute>
            }
          />

          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                {SettingsPage ? <SettingsPage /> : 
                <PlaceholderPage 
                  title="Settings" 
                  description="Manage your account and preferences" 
                />}
              </ProtectedRoute>
            }
          />

          {/* LEGACY REDIRECTS */}
          <Route path="/campaigns/new" element={<Navigate to="/form-submitter" replace />} />
          <Route path="/submit-forms" element={<Navigate to="/form-submitter" replace />} />
          <Route path="/ContactInformationForm" element={<Navigate to="/contact-info" replace />} />

          {/* 404 - Not Found */}
          <Route
            path="/404"
            element={
              <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="text-center">
                  <h1 className="text-6xl font-bold text-gray-300 mb-4">404</h1>
                  <p className="text-xl text-gray-600 mb-2">Page not found</p>
                  <p className="text-gray-500 mb-6">The page you're looking for doesn't exist.</p>
                  <button
                    onClick={() => window.location.href = user ? getDefaultPathForRole(user.role) : '/'}
                    className="px-6 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-all"
                  >
                    {user ? 'Go to Dashboard' : 'Go Home'}
                  </button>
                </div>
              </div>
            }
          />

          {/* Catch all - redirect to 404 */}
          <Route path="*" element={<Navigate to="/404" replace />} />
        </Route>
      </Routes>

      {/* Enhanced Auth Modal */}
      <AuthModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        view={view}
        onSwitchView={setView}
        onLogin={handleLogin}
        onRegister={handleRegister}
      />
    </>
  );
};

export default App;