import os
import json
import re
from google import genai
from decouple import config
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from .models import Task, SummarizedDocument, SharedMaterial, Quiz

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
            # Limit to first 15 pages to save memory
            page_limit = min(len(reader.pages), 15)
            for i in range(page_limit):
                text = reader.pages[i].extract_text()
                if text:
                    content += text + "\n"
                if len(content) > 50000: break # Hard cap at 50key characters
        elif extension in ['docx', 'doc']:
            import docx2txt
            content = docx2txt.process(file)
            if len(content) > 50000: content = content[:50000]
        else:
            # Try utf-8 first
            try:
                content = file.read().decode('utf-8')
            except:
                file.seek(0)
                content = file.read().decode('latin-1', errors='ignore')
            if len(content) > 50000: content = content[:50000]
    except Exception as e:
        print(f"Extraction error: {e}")
        return ""
        
    return content

def validate_content_quality(text, file_name):
    """
    Smart Buffer: Screens text for nonsense or total lack of academic/study relevance.
    Accepts informal notes, lists, and rough drafts. Rejects absolute junk.
    """
    if not text or len(text.strip()) < 50:
        return False, "This file is too short (under 50 characters). Please upload a document with more substantive content.", "N/A"

    api_key = config('GOOGLE_API_KEY', default='').strip()
    if not api_key:
        return True, "", "General" 
    
    client = genai.Client(api_key=api_key)
    snippet = text[:1500]
    
    prompt = (
        "You are a Content Gatekeeper for a Study App. Evaluate if this text has legitimate academic or study value.\n\n"
        "STRICT REJECTION CRITERIA:\n"
        "1. NONSENSE: Random characters, keyboard smashing, or repetitive symbols.\n"
        "2. FILLER/TESTING: Text that explicitly states it is 'nonsense', 'test', or 'whatever' just to fill space.\n"
        "3. META-HUMOR: Do NOT summarize the 'meta' meaning of nonsense. If the text is just someone saying 'this is nonsense yuhh', REJECT IT.\n"
        "4. TOTALLY UNRELATED: Shopping lists, private chat logs, or non-educational content.\n\n"
        "ACCEPTANCE CRITERIA:\n"
        "- Informal student notes, lecture summaries, rough drafts, exam prep, or any educational logic.\n\n"
        f"TEXT SNIPPET TO EVALUATE:\n{snippet}\n\n"
        "Respond ONLY with a JSON object: {\"is_valid\": boolean, \"reason\": \"string\", \"category\": \"string\"}"
    )

    try:
        # Fallback list for models if quota is reached
        models_to_try = ['gemini-2.0-flash', 'gemini-flash-latest', 'gemini-1.5-flash']
        response = None
        
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(model=model_name, contents=prompt)
                if response and response.text:
                    break
            except Exception as model_err:
                print(f"Validation Fallback: {model_name} failed, trying next...")
                continue

        # 1. Check for empty response
        if not response or not response.text:
            print(f"Validation Error: Empty response from AI for file {file_name}")
            return True, "", "General"

        # 2. Extract and Parse JSON
        try:
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if not match:
                return True, "", "General"
                
            data = json.loads(match.group())
            is_valid = data.get('is_valid')
            reason   = data.get('reason', "")
            category = data.get('category', "General")
            
            if not isinstance(is_valid, bool):
                return True, "", category
                
            # If rejected, use a polite generic message instead of the raw AI reason
            rejection_msg = "The document you have uploaded doesn't seem to be an academic text. Please try other documents."
            return is_valid, (rejection_msg if not is_valid else ""), category

        except json.JSONDecodeError:
            return True, "", "General"

    except Exception as e:
        print(f"Critical Validation Failure: {e}")
        return True, "", "General"

def validate_learning_reflection(reflection, task_title):
    """
    Screens for meaningful learning progress. 
    Allows short but substantive feedback. Rejects filler.
    """
    if not reflection or len(reflection.strip()) < 15:
        return False, "Your reflection is too short. Please share one specific thing you learned."

    api_key = config('GOOGLE_API_KEY', default='').strip()
    if not api_key:
        return True, "" # Skip validation if no API key
    
    client = genai.Client(api_key=api_key)
    
    prompt = (
        f"You are a Teacher checking a student's study reflection for the task: '{task_title}'.\n"
        "Evaluate if the student shared a meaningful or relevant takeaway.\n\n"
        "REJECT:\n"
        "- Generic filler like 'I learned a lot', 'Done', 'Asdasdasd', 'Test'.\n"
        "- Meta-comments like 'I am just doing this for the badge'.\n\n"
        "ACCEPT:\n"
        "- Any specific detail, concept, or summary of work done, even if informal.\n\n"
        f"STUDENT REFLECTION:\n{reflection}\n\n"
        "Respond ONLY with a JSON object: {\"is_valid\": boolean, \"reason\": \"string\"}"
    )

    try:
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            is_valid = data.get('is_valid', True)
            reason = data.get('reason', "Please provide a more educational takeaway.")
            return is_valid, reason
    except:
        pass
    
    return True, "" # Fallback to success on API error

def generate_document_summary(text, file_name='Document', file_mimetype='application/octet-stream'):
    """Generates a structured summary using Gemini AI with lazy initialization and smart fallback."""
    if not text:
        return "No content to summarize.", file_name

    # Step 1: Smart Buffer Validation
    is_valid, reason, category = validate_content_quality(text, file_name)
    if not is_valid:
        return f"⚠️ Notice: {reason or 'This content does not appear to be study-related or contains too much nonsense to summarize.'}", file_name

    # Lazy initialization: Always pull fresh key from .env
    api_key = config('GOOGLE_API_KEY', default='').strip()
    if not api_key:
        return "System Error: Missing AI API Key.", file_name
    
    client = genai.Client(api_key=api_key)

    try:
        # Standardized Structural Prompt (Updated for HTML rendering)
        prompt = (
            f"Summarize the document '{file_name}' for an academic setting. "
            "Your response MUST follow this exact structure with these exact emojis and formatting:\n\n"
            f"📄 <b>Document: {file_name}</b>\n\n"
            "📄 <b>Summary of:</b> [Space] [Summary Output]\n\n"
            "🔑 <b>Executive Highlights</b>\n"
            "1. [Highlight 1]\n"
            "2. [Highlight 2]\n\n"
            "🧱 <b>Three-Part Breakdown</b>\n"
            "1. <b>[Section Title]:</b> [Description]\n"
            "2. <b>[Section Title]:</b> [Description]\n"
            "3. <b>[Section Title]:</b> [Description]\n\n"
            "📌 <b>Key Details</b>\n"
            "[Essential facts/data]\n\n"
            "🚀 <b>Implications / Next Steps</b>\n"
            "[Context/Future study]\n\n"
            "💡 <b>Takeaway</b>\n"
            "[Final thought]\n\n"
            "STRICT RULES:\n"
            "1. No introductory banter.\n"
            "2. Ensure there is a SPACE after 'Summary of:' and before its output.\n"
            "3. ZERO space between ANY header and its output (Start content on the immediate NEXT line).\n"
            "4. For Three-Part Breakdown, always BOLD the category title before the colon: '1. <b>Title:</b> description'.\n"
            "5. Executive Highlights MUST be a numbered list (1., 2.).\n"
            f"TEXT CONTENT:\n{text[:8000]}"
        )
        
        # Standard fallback logic for model names
        models_to_try = [
            'gemini-2.0-flash',
            'gemini-flash-latest',
            'gemini-1.5-flash',
            'gemini-1.5-flash-8b'
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
                continue
        
        raise Exception(f"All AI models exhausted. Last error: {last_error}")

    except Exception as e:
        import traceback
        print(f"DEBUG - AI Summary Link Failure (Entering Offline Fallback): {e}")
        
        # MEMORY SAFETY: Limit fallback processing to first 20k chars
        safe_text = str(text)[:20000]
        raw_lines = safe_text.split('\n')
        processed_lines = []
        buffer = []
        
        for line in raw_lines:
            clean = line.strip()
            if not clean:
                if buffer:
                    processed_lines.append(" ".join(buffer))
                    buffer = []
                continue
            if re.match(r'^(\d+\.|\*|\-|[A-Z][a-z]+:)', clean):
                if buffer:
                    processed_lines.append(" ".join(buffer))
                    buffer = []
                processed_lines.append(clean)
            else:
                buffer.append(clean)
        
        if buffer:
            processed_lines.append(" ".join(buffer))
            
        cleaned_text = " ".join(processed_lines)
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
        
        sentences = [s.strip() for s in re.split(r'(?<=[\.\!\?]) +', cleaned_text) if len(s.strip()) > 15]
        summary_intro = " ".join(sentences[:6]) if sentences else "This document contains extensive academic study material."
        
        potential_points = []
        for line in processed_lines:
            line = line.strip()
            if len(line) > 10 and (re.match(r'^(\d+\.|\*|\-)', line) or (':' in line and line[:15].isupper())):
                potential_points.append(line)
            if len(potential_points) >= 10: break

        points_text = "".join([f"<li>{p}</li>" for p in potential_points]) if potential_points else "<li>Key focus: Detailed academic review and content extraction.</li>"

        fallback = (
            f"📄 <b>Document: {file_name}</b><br><br>"
            f"📄 <b>Summary of:</b> {summary_intro}<br><br>"
            f"🔑 <b>Executive Highlights</b><br>"
            f"<ul>{points_text}</ul><br>"
            f"💡 <b>Takeaway:</b> Review the document content for specific focus areas. Summary generated via offline fallback mode."
        )
        return fallback, f"Summary: {file_name}"

def calculate_user_metrics(user):
    """Calculates dashboard and progress analytics."""
    now = timezone.now()

    # 1. Basic Stats
    tasks_all       = Task.objects.filter(user=user)
    completed_tasks = tasks_all.filter(completed=True).count()
    verified_tasks  = tasks_all.filter(completed=True).exclude(reflection__isnull=True).exclude(reflection='').count()
    
    summaries_count  = SummarizedDocument.objects.filter(user=user).count()
    mastered_quizzes = Quiz.objects.filter(user=user, is_mastered=True).count()

    # 2. Level Calculation
    user_level = (completed_tasks // 5) + 1
    next_level_progress = ((completed_tasks % 5) / 5) * 100

    # 3. Study Streak
    streak = 0
    active_dates = set(
        list(tasks_all.filter(completed=True).values_list('created_at__date', flat=True)) +
        list(SummarizedDocument.objects.filter(user=user).values_list('created_at__date', flat=True))
    )
    
    check_day = timezone.now().date()
    while check_day in active_dates:
        streak += 1
        check_day -= timedelta(days=1)

    # 4. Weekly Hours Trend
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

    # 6. Special Habits
    # Night Owl: Completed a task between 10pm and 4am
    is_night_owl = tasks_all.filter(completed=True).filter(
        Q(completed_at__hour__gte=22) | Q(completed_at__hour__lt=4)
    ).exists()

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
        'verified_count':      verified_tasks,
        'mastered_count':      mastered_quizzes,
        'is_night_owl':        is_night_owl,
    }

def generate_batch_synthesis(doc_ids, user):
    """Synthesizes multiple summaries into one master study guide."""
    summaries_qs = SummarizedDocument.objects.filter(id__in=doc_ids, user=user)
    if not summaries_qs.exists():
        return "No summaries selected."

    # Build the collective text with file names
    numbered_summaries = []
    for i, s in enumerate(summaries_qs, 1):
        numbered_summaries.append(f"--- FILE {i}: {s.file_name} ---\n{s.summary_text}")
    
    combined_text = "\n\n".join(numbered_summaries)

    api_key = config('GOOGLE_API_KEY', default='')
    client = genai.Client(api_key=api_key)

    try:
        count = summaries_qs.count()
        prompt = (
            f"Produce a master 'Batch Summary' for {count} files. "
            f"START your response with the header: 📘 <b>Batch Summary ({count} Files)</b>, followed by a collective overview.\n\n"
            "Then, for EACH file provided, summarize its content using the exact same structure as individual files:\n"
            "📄 <b>Document [N]: [Filename]</b>\n\n"
            "📄 <b>Summary of:</b> [Space] [Intro]\n\n"
            "🔑 <b>Executive Highlights</b>\n"
            "1. [Highlight 1]\n"
            "2. [Highlight 2]\n\n"
            "🧱 <b>Three-Part Breakdown</b>\n"
            "1. <b>[Section Title]:</b> [Description]\n\n"
            "📌 <b>Key Details</b>\n"
            "🚀 <b>Implications / Next Steps</b>\n"
            "💡 <b>Takeaway</b>\n\n"
            "STRICT FORMATTING:\n"
            "1. NO introductory banter.\n"
            "2. Use HTML for structure.\n"
            "3. ZERO space between headers and their content (Start output on the NEXT line, NO GAPS).\n"
            "4. Add a SPACE after 'Summary of:' before the content.\n"
            "5. For Three-Part Breakdown, BOLD the section titles before the colon.\n"
            "6. Executive Highlights must be a numbered list.\n\n"
            f"DATA:\n{combined_text[:8000]}"
        )
        
        models_to_try = [
            'gemini-2.0-flash',
            'gemini-flash-latest',
            'gemini-1.5-flash'
        ]
        
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(model=model_name, contents=prompt)
                if response and response.text:
                    return response.text
            except:
                continue
        
        return "⚠️ All individual AI models failed for batch synthesis. Review individual summaries below."
    except Exception as e:
        return f"⚠️ [Batch Synthesis Unavailable]\n\n(Error: {str(e)})"

def search_summarized_documents(user, query):
    """Search for relevant summaries."""
    return SummarizedDocument.objects.filter(
        Q(user=user) & (Q(file_name__icontains=query) | Q(summary_text__icontains=query) | Q(subject__icontains=query))
    )

def chat_with_summary(old_summary, user_message):
    """Refines or modifies the summary based on user input using Gemini AI."""
    api_key = config('GOOGLE_API_KEY', default='').strip()
    if not api_key:
        return False, "System Error: Missing AI API Key."
    
    client = genai.Client(api_key=api_key)
    
    prompt = (
        f"You are a study assistant. Here is the current summary:\n\n{old_summary}\n\n"
        f"The user wants to make these changes: {user_message}\n\n"
        "Please provide the updated summary following the SAME structure and HTML formatting as before. "
        "Maintain the emojis and bolding. Return ONLY the updated summary text."
    )
    
    models_to_try = ['gemini-2.0-flash', 'gemini-flash-latest', 'gemini-1.5-flash']
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            if response and response.text:
                return True, response.text
        except Exception as e:
            print(f"Chat refinement error ({model_name}): {e}")
            continue
    return False, "I'm sorry, I couldn't reach the AI to update your summary. Please try again later."

def generate_quiz_from_summary(summary_text, num_questions=5):
    """Generates a multiple-choice quiz based on the provided summary text."""
    api_key = config('GOOGLE_API_KEY', default='').strip()
    if not api_key:
        return None
    
    client = genai.Client(api_key=api_key)
    
    # Strip HTML tags from summary before sending to AI for quiz generation
    clean_summary = re.sub(r'<[^>]*>', '', summary_text)
    
    prompt = (
        f"You are an expert educator. Based on the following study summary, create a {num_questions}-question multiple-choice quiz "
        "designed to test deep conceptual understanding and key facts. "
        "\n\nFor each question:\n"
        "1. Provide a clear, unambiguous question.\n"
        "2. Provide 4 distinct options (only one should be correct).\n"
        "3. Indicate the correct answer using exactly one letter: A, B, C, or D.\n"
        "\nIMPORTANT: Do NOT include 'A.', 'B.', 'C.', or 'D.' prefixes in the option strings themselves. "
        "Focus on the most important learning objectives identified in the summary. "
        "\n\nFormat the response as a valid JSON object with this exact structure: "
        "{\"quiz\": [{\"question\": \"...\", \"options\": [\"...\", \"...\", \"...\", \"...\"], \"answer\": \"A/B/C/D\"}, ...]}\n\n"
        f"SUMMARY CONTENT:\n{clean_summary[:8000]}"
    )
    
    models_to_try = ['gemini-2.0-flash', 'gemini-flash-latest', 'gemini-1.5-flash']
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            if response and response.text:
                # Extract JSON if the model returns it inside code blocks
                match = re.search(r'\{.*\}', response.text, re.DOTALL)
                if match:
                    quiz_data = json.loads(match.group())
                    return clean_quiz_data(quiz_data)
                quiz_data = json.loads(response.text)
                return clean_quiz_data(quiz_data)
        except Exception as e:
            print(f"Quiz Generation Error ({model_name}): {e}")
            continue
    return None

def clean_quiz_data(data):
    """Ensures quiz options don't have 'A.' prefixes and answers are standardized."""
    if not data or 'quiz' not in data:
        return data
        
    for q in data['quiz']:
        # Clean options: remove any "A. ", "1) ", etc prefixes if the AI added them
        if 'options' in q:
            q['options'] = [re.sub(r'^[A-Z0-9][\s\.\)\-‐\—]+', '', str(opt)).strip() for opt in q['options'] if opt]
            
        # Clean answer: ensure it's just A, B, C, or D
        if 'answer' in q:
            ans = str(q['answer']).strip().upper()
            match = re.search(r'[A-D]', ans)
            if match:
                q['answer'] = match.group()
            else:
                # Fallback if no letter found
                q['answer'] = 'A'
    return data
