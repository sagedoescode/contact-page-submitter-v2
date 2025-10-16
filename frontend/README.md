CPS - Contact Page Submitter
A high-volume web automation platform for scalable outreach campaigns with intelligent form submission and CAPTCHA bypass capabilities.
🚀 Features

High-Volume Processing: Handle millions of URLs efficiently with parallel processing
Smart CAPTCHA Bypass: Integrated DeathByCaptcha support for seamless automation
Intelligent Fallback: Automatically extract emails when forms aren't available
Role-Based Access: User, Admin, and Owner roles with tailored permissions
Detailed Analytics: Comprehensive charts and logs for tracking performance
API Integration: RESTful API for programmatic access and automation

📋 Prerequisites

Node.js 18+ and npm/yarn
Python 3.9+ (for backend)
PostgreSQL 13+ (for database)
DeathByCaptcha account (optional, for CAPTCHA solving)

🛠️ Installation

1. Clone the repository
   bashgit clone https://github.com/yourusername/contact-page-submitter.git
   cd contact-page-submitter
2. Install frontend dependencies
   bashnpm install

# or

yarn install 3. Configure environment variables
bashcp .env.example .env
Edit .env and add your configuration:
envVITE_API_BASE=http://localhost:8000 4. Start the development server
bashnpm run dev

# or

yarn dev
The application will be available at http://localhost:3000
📁 Project Structure
contact-page-submitter/
├── public/
│ └── assets/
│ └── images/
│ ├── CPS_Header_Logo.png
│ └── CPS_footer_logo.png
├── src/
│ ├── components/
│ │ ├── layout/
│ │ │ ├── AppLayout.jsx
│ │ │ ├── Header.jsx
│ │ │ └── Footer.jsx
│ │ ├── landing/
│ │ │ ├── HeroSection.jsx
│ │ │ ├── StepsSection.jsx
│ │ │ ├── FeaturesSection.jsx
│ │ │ ├── BenefitsSection.jsx
│ │ │ ├── TestimonialsSection.jsx
│ │ │ ├── GallerySection.jsx
│ │ │ ├── IntegrationsSection.jsx
│ │ │ └── FAQSection.jsx
│ │ ├── ui/
│ │ │ ├── button.jsx
│ │ │ ├── card.jsx
│ │ │ └── input.jsx
│ │ ├── AuthModal.jsx
│ │ └── UserMenu.jsx
│ ├── hooks/
│ │ └── useAuth.jsx
│ ├── pages/
│ │ ├── AccountPage.jsx
│ │ ├── AdminDashboard.jsx
│ │ ├── CampaignDetailPage.jsx
│ │ ├── CampaignsPage.jsx
│ │ ├── DashboardPage.jsx
│ │ ├── FormSubmitterPage.jsx
│ │ ├── LandingPage.jsx
│ │ ├── NewCampaignPage.jsx
│ │ ├── OwnerDashboard.jsx
│ │ ├── UserDashboard.jsx
│ │ └── ContactInformationForm.jsx
│ ├── services/
│ │ └── api.js
│ ├── App.jsx
│ ├── index.jsx
│ └── index.css
├── .env.example
├── .eslintrc.json
├── .gitignore
├── index.html
├── package.json
├── postcss.config.js
├── tailwind.config.js
├── vite.config.js
└── README.md
🚀 Deployment
Frontend Deployment (Vercel/Netlify)

Build the production bundle:

bashnpm run build

Deploy the dist folder to your hosting service

Backend Requirements
The frontend expects a backend API at the configured VITE_API_BASE URL with the following endpoints:

POST /api/auth/login - User authentication
POST /api/auth/register - User registration
GET /api/auth/me - Get current user
POST /api/submit/start - Start form submission campaign
GET /api/UserProfile/contact-answers - Get user profile
POST /api/UserProfile/upsert - Update user profile
GET /api/campaigns - List campaigns
POST /api/campaigns/create - Create new campaign

🔑 User Roles
User

Upload CSVs for processing
View personal campaign logs
Manage profile settings
Configure DeathByCaptcha credentials

Admin

All User permissions
View system-wide logs
Manage user accounts
Monitor all campaigns

Owner

All Admin permissions
System configuration
Global visibility
Full platform control

📊 Analytics Dashboard
The platform includes comprehensive analytics:

Submission Summary: Pie chart of contact forms, emails extracted, and errors
Volume Over Time: Line chart tracking submission trends
Top Domains: Bar chart of most contacted domains
CAPTCHA Analytics: Success rates and solve times
Error Breakdown: Detailed error categorization

🔧 Configuration
DeathByCaptcha Integration
Users can add their DeathByCaptcha credentials in their profile settings:

Navigate to User Profile
Enter DBC User ID and Password
Save settings

These credentials are used automatically during form submissions when CAPTCHAs are encountered.
📝 CSV Format
Upload CSVs should contain at minimum a website column:
csvwebsite,company,contact_name
https://example.com,Example Corp,John Doe
https://test.com,Test Inc,Jane Smith
🤝 Contributing

Fork the repository
Create your feature branch (git checkout -b feature/AmazingFeature)
Commit your changes (git commit -m 'Add some AmazingFeature')
Push to the branch (git push origin feature/AmazingFeature)
Open a Pull Request

📄 License
This project is licensed under the MIT License.
🆘 Support
For support, email support@cps-platform.com or open an issue on GitHub.
🔄 Version History

1.0.0 - Initial release with core functionality
Multi-role authentication system
CSV upload and processing
CAPTCHA bypass integration
Analytics dashboard

🎯 Roadmap

Webhook notifications
Advanced filtering options
Email template builder
A/B testing capabilities
API rate limiting controls
Export to multiple formats
Team collaboration features
