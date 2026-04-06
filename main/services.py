import os
import google.generativeai as genai
from django.db.models import Count, Sum
from .models import Task, SummarizedDocument, SharedMaterial
from django.utils import timezone
from datetime import timedelta

# Configure Gemini AI
from decouple import config
genai.configure(api_key=config('GOOGLE_API_KEY', default=''))

def extract_text_from_file(file):
    """
    Extracts text from PDF, DOCX, or plain text files.
    Note: Requires PyPDF2 and docx2txt to be installed.
    """
    extension = file.name.split('.')[-1].lower()
    content = ""
    
    try:
        if extension == 'pdf':
            import PyPDF2
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                content += page.extract_text() + "\n"
        elif extension in ['docx', 'doc']:
            import docx2txt
            content = docx2txt.process(file)
        else:
            content = file.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Extraction error: {e}")
        return ""
        
    return content

def generate_document_summary(text):
    """Generates a structured summary using Gemini AI."""
    if not text:
        return "No content to summarize."
        
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"Please provide a clear and concise summary of the following text, focused on key concepts for studying:\n\n{text[:10000]}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"AI Error: {e}")
        return "The AI was unable to summarize this document at this time."

def calculate_user_metrics(user):
    """Calculates dashboard and progress analytics."""
    now = timezone.now()
    week_ago = now - timedelta(days=7)

    # 1. Basic Stats
    tasks_all       = Task.objects.filter(user=user)
    completed_tasks = tasks_all.filter(completed=True).count()
    summaries_count = SummarizedDocument.objects.filter(user=user).count()
    
    # 2. Level Calculation
    user_level = (completed_tasks // 5) + 1
    next_level_progress = ((completed_tasks % 5) / 5) * 100

    # 3. Weekly Hours Trend (Summary count per day for last 7 days)
    weekly_hours_trend = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        day_h = (tasks_all.filter(completed=True, created_at__date=day).count() * 2) + \
                SummarizedDocument.objects.filter(user=user, created_at__date=day).count()
        weekly_hours_trend.append(day_h)

    # 4. Subject Distribution
    subject_qs = tasks_all.values('subject').annotate(count=Count('id')).order_by('-count')[:5]
    subject_labels = [s['subject'] or 'General' for s in subject_qs]
    subject_data   = [s['count'] for s in subject_qs]

    return {
        'user_level':          user_level,
        'next_level_progress': int(next_level_progress),
        'docs_count':          summaries_count,
        'completed_count':     completed_tasks,
        'total_tasks':         tasks_all.count(),
        'completion_rate':     round((completed_tasks / tasks_all.count() * 100), 1) if tasks_all.count() > 0 else 0,
        'study_hours':         (completed_tasks * 2) + summaries_count,
        'weekly_hours_trend':  weekly_hours_trend,
        'subject_labels':      subject_labels,
        'subject_data':        subject_data,
    }

def generate_batch_synthesis(summaries_qs):
    """Synthesizes multiple summaries into one master study guide."""
    combined_text = "\n\n".join([s.summary_text for s in summaries_qs])
    if not combined_text:
        return "No summaries selected."
        
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"Synthesize these individual study summaries into one master study guide:\n\n{combined_text[:10000]}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Synthesis error: {e}"

def search_summarized_documents(user, query):
    """Search for relevant summaries."""
    from django.db.models import Q
    return SummarizedDocument.objects.filter(
        Q(user=user) & (Q(file_name__icontains=query) | Q(summary_text__icontains=query) | Q(subject__icontains=query))
    )
