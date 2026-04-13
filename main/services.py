import os
from google import genai
from django.db.models import Count, Sum
from .models import Task, SummarizedDocument, SharedMaterial
from django.utils import timezone
from datetime import timedelta
import re

# Configure Gemini AI
from decouple import config
# Note: ai_client is now initialized dynamically inside functions to ensure .env updates are respected.

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
    """Generates a structured summary using Gemini AI with lazy initialization and smart fallback."""
    if not text:
        return "No content to summarize.", file_name

    # Lazy initialization: Always pull fresh key from .env
    api_key = config('GOOGLE_API_KEY', default='').strip()
    if not api_key:
        return "System Error: Missing AI API Key.", file_name
    
    client = genai.Client(api_key=api_key)

    try:
        # Standardized Structural Prompt (Follows USER's 2026-04-09 Guidelines)
        prompt = (
            f"Summarize the document '{file_name}' for an academic setting. "
            "Follow these rules strictly:\n"
            "1. ACCURACY: Reflect the original meaning without filler or unrelated text.\n"
            "2. FORMAT: Use clear, concise sentences. Use bullet points for readability. "
            "   Short text -> 2-3 sentences. Long text -> 5-7 bullet points.\n"
            "3. CONTENT: Capture the main idea, key arguments, and essential facts. "
            "   Answer: What is this about? What are the main takeaways?\n"
            "4. OUTPUT: Provide ONLY the summary. No commentary. "
            "   Use HTML tags (<b>, <ul>, <li>) for structure. "
            "   End with a one-line 'CORE TAKEAWAY' in a <b> tag.\n\n"
            f"TEXT CONTENT:\n{text[:12000]}"
        )
        # ── Multi-Model Resilient Generation ──
        models_to_try = [
            'gemini-2.0-flash',  # High priority (Experimental/New)
            'gemini-1.5-flash',  # Robust fallback
            'gemini-small'       # Last resort API-wise
        ]
        
        last_error = "Unknown error"
        for model_name in models_to_try:
            try:
                print(f"DEBUG - Attempting summary with {model_name}...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    summary_text = response.text
                    first_line = summary_text.strip().split('\n')[0][:80]
                    title_line = first_line if len(first_line) > 5 else file_name
                    return summary_text, title_line
            except Exception as model_err:
                last_error = str(model_err)
                print(f"DEBUG - {model_name} failed: {last_error[:100]}")
                continue # Try next model
        
        # If we get here, all models failed (likely 429 or 401)
        raise Exception(f"All AI models exhausted. Last error: {last_error}")

    except Exception as e:
        import traceback
        print(f"DEBUG - AI Summary Link Failure: {e}")
        print(traceback.format_exc())
        
        # --- AGGRESSIVE VERTICAL TEXT REPAIR ---
        # 1. First Pass: Join lines that are likely part of the same sentence
        raw_lines = text.split('\n')
        processed_lines = []
        buffer = []
        
        for line in raw_lines:
            clean = line.strip()
            if not clean:
                if buffer:
                    processed_lines.append(" ".join(buffer))
                    buffer = []
                continue
            
            # If line is a list item or start of a new section, flush buffer
            if re.match(r'^(\d+\.|\*|\-|[A-Z][a-z]+:)', clean):
                if buffer:
                    processed_lines.append(" ".join(buffer))
                    buffer = []
                processed_lines.append(clean)
            else:
                # Append to buffer (it's likely a continuation)
                buffer.append(clean)
        
        if buffer:
            processed_lines.append(" ".join(buffer))
            
        # 2. Second Pass: Synthesize into a readable summary format
        cleaned_text = " ".join(processed_lines)
        # Fix double spaces and common PDF artifacts
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
        
        # Extract more meaningful sentences for a deeper overview
        sentences = [s.strip() for s in re.split(r'(?<=[.!?]) +', cleaned_text) if len(s.strip()) > 15]
        # Include more sentences to 'capture the thought' (approx 6 sentences)
        summary_intro = " ".join(sentences[:6]) if sentences else "This document contains extensive academic study material."
        
        # Extract up to 10 logical points or numbered items
        potential_points = []
        for line in processed_lines:
            line = line.strip()
            # Look for numbered items or capital letter headers
            if len(line) > 10 and (re.match(r'^(\d+\.|\*|\-)', line) or (':' in line and line[:15].isupper())):
                potential_points.append(line)
            if len(potential_points) >= 10: break

        points_text = "".join([f"<li>{p}</li>" for p in potential_points]) if potential_points else "<li>Key focus: Detailed academic review and content extraction.</li>"

        fallback = (
            f"📌 <b style='color:#8C1007'>DETAILED SUMMARY OVERVIEW (OFFLINE)</b><br><br>"
            f"{summary_intro}<br><br>"
            f"🔍 <b>KEY EXTRACTED POINTS:</b><br>"
            f"<ul>{points_text}</ul><br>"
            f"<b>CORE TAKEAWAY:</b> Based on the extracted content, this document provides a comprehensive look at {file_name}. Review the sections above for detailed insights."
        )
        return fallback, f"Summary: {file_name}"

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
    
    # Get all active dates from both tasks and summaries in one go
    active_dates = set(
        list(tasks_all.filter(completed=True).values_list('created_at__date', flat=True)) +
        list(SummarizedDocument.objects.filter(user=user).values_list('created_at__date', flat=True))
    )
    
    check_day = timezone.now().date()
    while check_day in active_dates:
        streak += 1
        check_day -= timedelta(days=1)

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

    # Initialize client dynamically
    api_key = config('GOOGLE_API_KEY', default='')
    client = genai.Client(api_key=api_key)

    try:
        prompt = (
            "Synthesize these individual study summaries into one master study guide. "
            "Follow these rules strictly:\n"
            "1. ACCURACY: Merge content without distortion or filler.\n"
            "2. FORMAT: Use clear sentences and bullet points. Focus on logical categorization.\n"
            "3. OUTPUT: Provide ONLY the synthesis. End with a one-line 'CORE TAKEAWAY' for the entire batch.\n\n"
            f"SUMMARIES:\n{combined_text[:10000]}"
        )
        # ── Multi-Model Resilient Synthesis ──
        models_to_try = ['gemini-2.0-flash', 'gemini-1.5-flash']
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                print(f"Batch Synthesis Error with {model_name}: {e}")
                continue
        
        return "⚠️ All individual AI models failed for batch synthesis. Review individual summaries below."
    except Exception as e:
        print(f"Synthesis Error: {e}")
        return f"⚠️ [Batch Synthesis Unavailable]\n\nThe AI was unable to combine these documents. Please review the individual summaries below.\n\n(Error: {str(e)})"

def search_summarized_documents(user, query):
    """Search for relevant summaries."""
    from django.db.models import Q
    return SummarizedDocument.objects.filter(
        Q(user=user) & (Q(file_name__icontains=query) | Q(summary_text__icontains=query) | Q(subject__icontains=query))
    )
