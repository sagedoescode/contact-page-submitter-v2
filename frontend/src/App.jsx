// src/App.jsx - Complete Version with Correct Routing
import React, { useState, useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "react-hot-toast";
import useAuth from "./hooks/useAuth";
import AuthModal from "./components/AuthModal";
import AppLayout from "./components/layout/AppLayout";

// Import all pages
import UserDashboard from "./pages/UserDashboard";
import AdminDashboard from "./pages/AdminDashboard";
import OwnerDashboard from "./pages/OwnerDashboard";
import ContactInformationForm from "./pages/ContactInformationForm";
import CampaignDetailPage from "./pages/CampaignDetailPage";
import ActivityPage from "./pages/ActivityPage";
import LandingPage from "./pages/LandingPage";
import DashboardPage from "./pages/DashboardPage";
import CampaignsPage from "./pages/CampaignsPage";
import FormSubmitterPage from "./pages/FormSubmitterPage";

// Loading Component with Enhanced Styling
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
    // Save attempted location for redirect after login
    sessionStorage.setItem('redirectAfterLogin', location.pathname);
    return <Navigate to="/" replace />;
  }

  // Check role permissions
  if (allowedRoles.length > 0 && !allowedRoles.includes(user.role)) {
    return <Navigate to="/dashboard" replace />;
  }

  // Check if contact info is required and filled
  if (requiresContactInfo && (!user.contactInfoCompleted)) {
    // Don't redirect if we're already on the contact info page
    if (location.pathname !== '/contact-info') {
      sessionStorage.setItem('redirectAfterContactInfo', location.pathname);
      return <Navigate to="/contact-info" replace />;
    }
  }

  return children;
};

const App = () => {
  const { user, loading, login, register } = useAuth();
  const [showModal, setShowModal] = useState(false);
  const [view, setView] = useState("login");
  const location = useLocation();

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

  // Show loading screen while checking auth
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
      // Check for redirect
      const redirect = sessionStorage.getItem('redirectAfterLogin');
      if (redirect) {
        sessionStorage.removeItem('redirectAfterLogin');
        window.location.href = redirect;
      }
    }
    return result;
  };

  const handleRegister = async (userData) => {
    const result = await register(userData);
    if (result.success) {
      setShowModal(false);
    }
    return result;
  };

  return (
    <>
      {/* Enhanced Toast Notifications - Optimized for Campaign Processing */}
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
            iconTheme: {
              primary: "#10b981",
              secondary: "#ffffff"
            },
            style: {
              background: "#f0fdf4",
              color: "#166534",
              border: "1px solid #86efac"
            },
            duration: 4000,
          },
          error: {
            iconTheme: {
              primary: "#ef4444",
              secondary: "#ffffff"
            },
            style: {
              background: "#fef2f2",
              color: "#991b1b",
              border: "1px solid #fca5a5"
            },
            duration: 8000, // Longer for campaign errors
          },
          loading: {
            style: {
              background: "#f3f4f6",
              color: "#374151",
            },
            duration: Infinity, // Campaign processing can take time
          },
          // Custom styling for campaign-related toasts
          className: 'campaign-toast',
        }}
      />

      {/* Main Routes */}
      <Routes>
        <Route element={<AppLayout />}>
          {/* Public Routes */}
          <Route
            index
            element={
              user ? (
                <Navigate to="/dashboard" replace />
              ) : (
                <LandingPage
                  onLogin={() => openModal("login")}
                  onRegister={() => openModal("register")}
                />
              )
            }
          />

          {/* Protected Routes */}

          {/* Main dashboard - renders based on user role */}
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />

          {/* Activity page */}
          <Route
            path="/activity"
            element={
              <ProtectedRoute>
                <ActivityPage />
              </ProtectedRoute>
            }
          />

          {/* Campaigns Management - View All Campaigns */}
          <Route
            path="/campaigns"
            element={
              <ProtectedRoute>
                <CampaignsPage />
              </ProtectedRoute>
            }
          />

          {/* Form Submitter - Main route for creating new campaigns */}
          <Route
            path="/form-submitter"
            element={
              <ProtectedRoute requiresContactInfo={false}>
                <FormSubmitterPage
                  enableRealTimeProgress={true}
                  enableAdvancedValidation={true}
                  showPerformanceMetrics={true}
                />
              </ProtectedRoute>
            }
          />

          {/* Legacy route for campaign creation - redirect to form-submitter */}
          <Route
            path="/campaigns/new"
            element={
              <Navigate to="/form-submitter" replace />
            }
          />

          {/* Alternative legacy route */}
          <Route
            path="/submit-forms"
            element={
              <Navigate to="/form-submitter" replace />
            }
          />

          {/* Individual campaign detail page */}
          <Route
            path="/campaigns/:campaignId"
            element={
              <ProtectedRoute>
                <CampaignDetailPage />
              </ProtectedRoute>
            }
          />

          {/* Campaign results/statistics */}
          <Route
            path="/campaigns/:campaignId/results"
            element={
              <ProtectedRoute>
                <CampaignDetailPage showResultsView={true} />
              </ProtectedRoute>
            }
          />

          {/* Contact Information Form */}
          <Route
            path="/contact-info"
            element={
              <ProtectedRoute>
                <ContactInformationForm />
              </ProtectedRoute>
            }
          />

          {/* Legacy path for Contact Information Form */}
          <Route
            path="/ContactInformationForm"
            element={
              <Navigate to="/contact-info" replace />
            }
          />

          {/* User specific dashboard route */}
          <Route
            path="/user"
            element={
              <ProtectedRoute allowedRoles={["user"]}>
                <UserDashboard />
              </ProtectedRoute>
            }
          />

          {/* Admin specific dashboard route */}
          <Route
            path="/admin"
            element={
              <ProtectedRoute allowedRoles={["admin"]}>
                <AdminDashboard />
              </ProtectedRoute>
            }
          />

          {/* Owner specific dashboard route */}
          <Route
            path="/owner"
            element={
              <ProtectedRoute allowedRoles={["owner"]}>
                <OwnerDashboard />
              </ProtectedRoute>
            }
          />

          {/* Settings page */}
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <div className="min-h-screen bg-gray-50 p-8">
                  <div className="max-w-4xl mx-auto">
                    <h1 className="text-2xl font-bold mb-4">Settings</h1>
                    <div className="bg-white rounded-lg shadow p-6">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                          <h3 className="font-semibold mb-2">Campaign Settings</h3>
                          <p className="text-gray-600 text-sm">Default settings for new campaigns</p>
                        </div>
                        <div>
                          <h3 className="font-semibold mb-2">Automation Settings</h3>
                          <p className="text-gray-600 text-sm">Browser and processing preferences</p>
                        </div>
                      </div>
                      <div className="mt-6 p-4 bg-blue-50 rounded-lg">
                        <p className="text-blue-700">Settings page coming soon with campaign automation preferences...</p>
                      </div>
                    </div>
                  </div>
                </div>
              </ProtectedRoute>
            }
          />

          {/* Help/Documentation page */}
          <Route
            path="/help"
            element={
              <ProtectedRoute>
                <div className="min-h-screen bg-gray-50 p-8">
                  <div className="max-w-4xl mx-auto">
                    <h1 className="text-2xl font-bold mb-4">Help & Documentation</h1>
                    <div className="bg-white rounded-lg shadow p-6">
                      <div className="space-y-6">
                        <section>
                          <h3 className="font-semibold text-lg mb-2">Getting Started</h3>
                          <ul className="list-disc pl-5 space-y-2 text-gray-600">
                            <li>Complete your contact information</li>
                            <li>Upload a CSV file with website URLs</li>
                            <li>Configure campaign settings</li>
                            <li>Monitor progress in real-time</li>
                          </ul>
                        </section>
                        <section>
                          <h3 className="font-semibold text-lg mb-2">CSV Format Requirements</h3>
                          <p className="text-gray-600">Your CSV must contain a column named 'website', 'url', 'domain', or 'site' with one URL per row.</p>
                        </section>
                        <section>
                          <h3 className="font-semibold text-lg mb-2">Campaign Processing</h3>
                          <ul className="list-disc pl-5 space-y-2 text-gray-600">
                            <li>Processing speed: ~120 websites per hour</li>
                            <li>Automatic CAPTCHA solving included</li>
                            <li>Email fallback when no contact form found</li>
                            <li>Real-time progress tracking</li>
                          </ul>
                        </section>
                      </div>
                    </div>
                  </div>
                </div>
              </ProtectedRoute>
            }
          />

          {/* 404 - Not Found */}
          <Route
            path="/404"
            element={
              <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-purple-50 to-pink-50 flex items-center justify-center">
                <div className="text-center">
                  <h1 className="text-6xl font-bold text-gray-300 mb-4">404</h1>
                  <p className="text-xl text-gray-600 mb-2">Page not found</p>
                  <p className="text-gray-500 mb-6">The page you're looking for doesn't exist.</p>
                  <button
                    onClick={() => window.location.href = user ? '/dashboard' : '/'}
                    className="px-6 py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg hover:from-indigo-700 hover:to-purple-700 transition-all transform hover:scale-105"
                  >
                    {user ? 'Go to Dashboard' : 'Go Home'}
                  </button>
                </div>
              </div>
            }
          />

          {/* Catch all - redirect to 404 */}
          <Route
            path="*"
            element={<Navigate to="/404" replace />}
          />
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