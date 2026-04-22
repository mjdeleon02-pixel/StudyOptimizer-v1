# 🎓 StudyOptimizer - AI-Powered Academic Command Center

StudyOptimizer is a premium, all-in-one web application designed to streamline student workflows through AI-powered document analysis, intelligent task management, and interactive study planning.

![StudyOptimizer Dashboard](https://github.com/user-attachments/assets/dashboard_mockup_placeholder)

## ✨ Core Features

### 📄 AI Document Summarizer
* **Intelligent Synthesis**: Upload academic PDFs or documents and receive structured, sponsor-ready summaries via Gemini AI.
* **Knowledge Persistence**: Automatically save summaries to your personal library and share them with the community.

### 🧠 AI Smart Quiz & Chat
* **Instant Quiz Generation**: Transform your study summaries into interactive multiple-choice quizzes to test your knowledge.
* **Study Assistant Chat**: Refine your summaries in real-time by chatting with the AI (e.g., "Make this simpler" or "Explain the main formulas").

### 📅 Interactive Study Schedule
* **Personalized Planner**: Directly add and manage weekly study sessions through a sleek, modal-based interface (accessible from the Dashboard).
* **Real-Time Updates**: Instant visual feedback when adding or removing schedule items.

### 🔧 Task Manager & Progress Tracking
* **Smart Organization**: Categorize tasks by subject and priority.
* **Accuracy-Driven Metrics**: Real-time calculation of **Study Streaks**, **Completion Rates**, and **AI-Verified Reflections**.

### 👤 Profile & Gamification
* **Level System**: Progress through levels for every 5 completed tasks.
* **Achievements**: Unlock trophies like "Night Owl," "Mastery Badge," and "Study Starter."

---

## 🛠️ Tech Stack

### Backend
* **Python 3.12** & **Django**: Secure and scalable core architecture.
* **Gemini AI**: High-performance AI for summarization, chat, and quiz logic.
* **PostgreSQL / SQLite**: Flexible database options.
* **Cloudinary**: Cloud-based storage for study materials.

### Frontend
* **Tailwind CSS**: Premium, glassmorphic UI.
* **Alpine.js**: Reactive state-management.
* **Lucide Icons** & **Chart.js**: High-quality visuals and data tracking.

---

## 🚀 Getting Started

### Prerequisites
* **Python 3.12+**
* **Docker** (Optional, for containerized setup)
* **Google Gemini API Key** (Set in `.env`)

### Option 1: Manual Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/mardnts28/Study_Optimizer.git
   cd StudyOptimizer-v1
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Setup Environment**:
   Create a `.env` file based on `.env.example` and add your `GOOGLE_API_KEY`.

4. **Database Migration**:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

5. **Run Server**:
   ```bash
   python manage.py runserver
   ```

### Option 2: Docker Installation (Recommended)

1. **Build and Start**:
   ```bash
   docker-compose up --build
   ```
2. **Access the app** at `http://127.0.0.1:8000/`.

---

## 📂 Project Structure

```text
Study_Optimizer/
├── main/               # Core application logic
├── studyoptimizer/     # Project settings & configuration
├── manage.py           # Django administrative utility
├── Dockerfile          # Container configuration
├── docker-compose.yml  # Multi-container orchestration
└── README.md           # Documentation
```

---

## 🔒 Security & Best Practices
* **STRIDE Threat Modeling**: Protection against Spoofing, Tampering, and Elevation of Privilege.
* **CSRF & CSP Protection**: Hardened security headers and form validation.
* **MFA (Optional)**: Support for TOTP-based Multi-Factor Authentication.

---

*Built with ❤️ for students, by the StudyOptimizer team.*
LICENSE` for more information.

---
*Built with ❤️ for students, by the StudyOptimizer team.*
