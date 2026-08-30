# HCG Knowledge Centre

An advanced, role-secured Learning Management System (LMS) built with Python, Flask, and SQLite. It features course management, interactive assessments, a gamified rewards wallet, community social feeds, and a comprehensive REST API.

## 📂 Documentation

Technical documentation and architecture details are located in the docs/ folder:
- docs/database_er_diagram.md - Complete SQLite database schema and ER diagram.
- docs/cloud_hosting_architecture.md - Production cloud deployment & security guide.

## ✨ Key Features

- **Role-Based Access Control:** Distinct experiences for dmin, moderator, and asic user (students).
- **Course & Assessment Engine:** Interactive course assignments, tests, and auto-generated certificates.
- **Rewards System & Gamification:** A transactional wallet that awards points for completing courses and engaging in the community.
- **Community Feed:** A social timeline for knowledge sharing, commenting, and upvoting content.
- **Developer API (v1):** A fully-featured REST API with API Key authentication, interactive playground, and full CRUD support.

---

## 🚀 Setup & Installation

### Prerequisites
- Python 3.8+ 
- SQLite3 (Included with standard Python)

### 1. Clone the Repository
`ash
git clone <repository_url>
cd hcg-knowledge-centre
`

### 2. Create a Virtual Environment
It's recommended to run the app in an isolated virtual environment.
`ash
# On Windows
python -m venv venv
venv\Scripts\activate

# On macOS/Linux
python3 -m venv venv
source venv/bin/activate
`

### 3. Install Dependencies
Install the required packages from equirements.txt:
`ash
pip install -r requirements.txt
`

### 4. Initialize the Database
The application uses SQLite (users.db). The database is auto-initialized with seeded demo data when the app runs for the first time.

### 5. Run the Application
Start the Flask development server:
`ash
python app.py
`

The application will be accessible at: **http://127.0.0.1:5000**

---

## 📖 Usage Guide

### Initial Login
If you used the auto-seeder, you can log in with:
- **Admin:** dmin / dmin
- **Moderator:** mod / mod
- **Student:** student / student
*(Ensure you change these in a production environment!)*

### Admin Dashboard (/admin)
- **Manage Content:** Create courses, assign them to individual students or groups, and build question banks.
- **Manage Users:** Provision new user accounts, update roles, or off-board members.
- **Reward Settings:** Manually adjust student wallet balances or settle point redemptions.
- **API Access:** Generate, view, copy, or revoke API Keys for third-party integrations.

### REST API Playground (/api/v1/docs)
- Go to the API Documentation link in the navigation menu.
- Input your X-API-Key and X-API-Secret obtained from the Admin Dashboard.
- Use the interactive interface to send live test queries (cURL, Python) directly into the database.

---

## 🛠 Tech Stack
- **Backend:** Python 3, Flask, Werkzeug
- **Database:** SQLite3
- **Frontend:** HTML5, Tailwind CSS (via CDN), custom JavaScript, Jinja2 Templates
- **Data parsing:** openpyxl (for Excel question imports)
