import os
from google import genai
from django.db.models import Count, Sum
from .models import Task, SummarizedDocument, SharedMaterial
from django.utils import timezone
from datetime import timedelta

# Configure Gemini AI
from decouple import config
ai_client = genai.Client(api_key=config('GOOGLE_API_KEY', default=''))

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

def generate_document_summary(text, file_name='Document'):
    """Generates a structured summary using Gemini AI. Returns (summary_text, title_line)."""
    if not text:
        return "No content to summarize.", file_name

    try:
        prompt = (
            f"You are a study assistant. Summarize the following document titled '{file_name}' "
            f"clearly and concisely for a student. Focus on key concepts, definitions, and important points.\n\n"
            f"{text[:10000]}"
        )
        response = ai_client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        summary_text = response.text
        # Extract a short title from the first line if possible
        first_line = summary_text.strip().split('\n')[0][:120]
        title_line = first_line if first_line else file_name
        return summary_text, title_line
    except Exception as e:
        print(f"AI Error: {e}")
        fallback = "The AI was unable to summarize this document at this time."
        return fallback, file_name

def calculate_user_metrics(user):
    """Calculates dashboard and progress analytics."""
    now = timezone.now()

    # 1. Basic Stats
    tasks_all       = Task.objects.filter(user=user)
    completed_tasks = tasks_all.filter(completed=True).count()
    summaries_count = SummarizedDocument.objects.filter(user=user).count()

    # 2. Level Calculation
    user_level = (completed_tasks // 5) + 1
    next_level_progress = ((completed_tasks % 5) / 5) * 100

    # 3. Study Streak (consecutive days with completed tasks)
    streak = 0
    check_day = now.date()
    for _ in range(365):
        had_activity = (
            tasks_all.filter(completed=True, created_at__date=check_day).exists() or
            SummarizedDocument.objects.filter(user=user, created_at__date=check_day).exists()
        )
        if had_activity:
            streak += 1
            check_day -= timedelta(days=1)
        else:
            break

    # 4. Weekly Hours Trend (last 7 days)
    weekly_hours_trend = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        day_h = (tasks_all.filter(completed=True, created_at__date=day).count() * 2) + \
                SummarizedDocument.objects.filter(user=user, created_at__date=day).count()
        weekly_hours_trend.append(day_h)

    # 5. Subject Distribution
    subject_qs = tasks_all.values('subject').annotate(count=Count('id')).order_by('-count')[:5]
    subject_labels = [s['subject'] or 'General' for s in subject_qs]
    subject_data   = [s['count'] for s in subject_qs]

    total = tasks_all.count()
    return {
        'user_level':          user_level,
        'next_level_progress': int(next_level_progress),
        'docs_count':          summaries_count,
        'summaries_count':     summaries_count,
        'completed_count':     completed_tasks,
        'total_tasks':         total,
        'completion_rate':     round((completed_tasks / total * 100), 1) if total > 0 else 0,
        'study_hours':         (completed_tasks * 2) + summaries_count,
        'streak':              streak,
        'weekly_hours_trend':  weekly_hours_trend,
        'subject_labels':      subject_labels,
        'subject_data':        subject_data,
    }

def generate_batch_synthesis(doc_ids, user):
    """Synthesizes multiple summaries into one master study guide."""
    summaries_qs = SummarizedDocument.objects.filter(id__in=doc_ids, user=user)
    combined_text = "\n\n".join([s.summary_text for s in summaries_qs])
    if not combined_text:
        return "No summaries selected."

    try:
        prompt = f"Synthesize these individual study summaries into one master study guide:\n\n{combined_text[:10000]}"
        response = ai_client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Synthesis error: {e}"

def search_summarized_documents(user, query):
    """Search for relevant summaries."""
    from django.db.models import Q
    return SummarizedDocument.objects.filter(
        Q(user=user) & (Q(file_name__icontains=query) | Q(summary_text__icontains=query) | Q(subject__icontains=query))
    )
