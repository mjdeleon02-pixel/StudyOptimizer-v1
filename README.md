# 🎓 StudyOptimizer - AI-Powered Academic Command Center

StudyOptimizer is a premium, all-in-one web application designed to streamline student workflows through AI-powered document analysis, intelligent task management, and interactive study planning.

![StudyOptimizer Dashboard](https://github.com/user-attachments/assets/dashboard_mockup_placeholder)

## ✨ Core Features

### 📄 AI Document Summarizer
* **Intelligent Synthesis**: Upload academic PDFs or documents and receive structured, sponsor-ready summaries.
* **Knowledge Persistence**: Automatically save summaries to your personal library and share them with the community.
* **Estimated Study Value**: Each document summarized contributes **1 hour** to your total study time.

### 📅 Interactive Study Schedule
* **Personalized Planner**: Directly add and manage weekly study sessions through a sleek, modal-based interface (accessible from the Dashboard).
* **Real-Time Updates**: Instant visual feedback when adding or removing schedule items.
* **Color-Coded Activities**: Visual categorization of study blocks for better scanability.

### 🔧 Task Manager & Progress Tracking
* **Smart Organization**: Categorize tasks by subject and priority.
* **Accuracy-Driven Metrics**: Real-time calculation of **Study Streaks** and **Completion Rates**.
* **Real Study Hours**: Automatically estimates study time—**2 hours** per completed task.

### 👤 Profile & Gamification
* **Level System**: Level up your academic journey! Every 5 completed tasks progress you to the next level (e.g., Level 1 "Rising Star").
* **Achievements**: Unlock trophies like "Study Starter," "7-Day Streak," and "Speed Learner" as you hit real milestones.
* **Global Stats**: Track your total documents, task success rate, and cumulative study hours at a glance.

### 🤝 Strategic Collaboration
* **Shared Repository**: Access and like study materials shared by other students in the "Collaborate" hub.
* **Interactive Comments**: Engage in academic discussions directly on shared summaries.

### 🔔 Smart Notification Hub
* **Real-Time Deadlines**: A non-intrusive dropdown hub that automatically tracks your upcoming task deadlines and alerts you to urgent priorities.

---

## 🛠️ Tech Stack

### Backend
* **Django**: Robust Python framework for secure and scalable architecture.
* **PostgreSQL / SQLite**: Flexible database options for high-performance data persistence.
* **Cloudinary**: Cloud-based storage for securely managing and serving student-uploaded study materials.
* **Python-Docx & PyPDF2**: Backend libraries for deep document parsing.

### Frontend
* **Tailwind CSS**: Utility-first CSS framework for a premium, glassmorphic UI.
* **Alpine.js**: Lightweight JavaScript framework for reactive state-management and interactivity.
* **Lucide Icons**: Consistent, high-quality iconography across the platform.
* **Chart.js**: Interactive data visualization for your Weekly Activity trend.

---

## 🚀 Getting Started

### Prerequisites
* Python 3.8+
* Pip (Python package manager)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/mardnts28/StudyOptimizer.git
   cd Study_Optimizer
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   *Alternatively, install core packages individually:*
   ```bash
   pip install django PyPDF2 python-docx cloudinary django-cloudinary-storage python-decouple
   ```

3. **Database Migration**:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

4. **Run Server**:
   ```bash
   python manage.py runserver
   ```
   Access the app at `http://127.0.0.1:8000/`.

---

## 📂 Project Structure

```text
Study_Optimizer/
├── main/               # Core application logic
│   ├── models.py       # Data definitions (Task, Schedule, Summary, SharedMaterial, Comment)
│   ├── views.py        # Controller logic & API endpoints (Real-time calculations)
│   ├── urls.py         # App-specific routing
│   └── templates/      # Premium HTML interfaces with Alpine.js & Tailwind
├── studyoptimizer/     # Project settings & configuration
├── manage.py           # Django administrative utility
└── README.md           # Documentation
```

---

## 🔒 Security
StudyOptimizer implements standard Django security practices, including:
* Secure authentication and session management.
* CSRF protection on all interactive forms.
* Login requirements for all data-sensitive pages.
* Password strength validation on registration.

---

## 📝 License
Distributed under the MIT License. See `LICENSE` for more information.

---
*Built with ❤️ for students, by the StudyOptimizer team.*
