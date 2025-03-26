# INFO
# - MAX requests per minute = [FREE: 15], [TIER 1: 2000], [TIER 2: 10,000]

import requests as r
from time import sleep
import json
from math import ceil
import os
import sys
import traceback # For better error reporting
import threading
import queue # For thread-safe communication

# --- GUI Imports ---
import customtkinter as ctk
from tkinter import messagebox, simpledialog, filedialog # Keep standard dialogs
from tkinter import StringVar, IntVar, BooleanVar, END

# --- PDF Generation Imports ---
try:
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        PageBreak,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER
    from reportlab.lib.units import inch
    from reportlab.lib.colors import black, navy, gray

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    # We'll show a warning in the GUI if PDF is selected but library is missing
# --- End PDF Imports ---


# ----- ORIGINAL SCRIPT FUNCTIONS & VARIABLES (Adapted for GUI) ----- #

# Create a directory to store book files if it doesn't exist
OUTPUT_DIR = "books"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Constants ---
QUOTA_EXCEEDED_ERROR_STRING = "QUOTA_EXCEEDED"
MAX_GENERATION_ATTEMPTS = 4 # Max attempts for generating a single piece (chapter/sub/outline chunk)
OUTLINE_CHUNK_THRESHOLD = 15 # Generate outline in chunks if total items > this
CHAPTERS_PER_OUTLINE_CHUNK = 3 # How many chapters to outline per API call in chunked mode

# Queue for GUI updates from the worker thread
gui_queue = queue.Queue()

# --- GUI Interaction Functions ---

def log_message(message):
    """Safely logs a message to the GUI text area from any thread."""
    gui_queue.put(("log", str(message)))

def ask_question_gui(title, question):
    """Safely asks a yes/no question from the worker thread."""
    result_queue = queue.Queue()
    gui_queue.put(("askyesno", (title, question, result_queue)))
    return result_queue.get() # Wait for the result from the main thread

def ask_string_gui(title, prompt):
    """Safely asks for string input from the worker thread."""
    result_queue = queue.Queue()
    gui_queue.put(("askstring", (title, prompt, result_queue)))
    return result_queue.get() # Wait for the result from the main thread

def show_info_gui(title, message):
    """Safely shows an info message box from the worker thread."""
    gui_queue.put(("showinfo", (title, message)))

def show_error_gui(title, message):
    """Safely shows an error message box from the worker thread."""
    gui_queue.put(("showerror", (title, message)))

def show_warning_gui(title, message):
    """Safely shows a warning message box from the worker thread."""
    gui_queue.put(("showwarning", (title, message)))


# --- PDF Generation Function (GUI Adapted) ---
def generate_pdf_from_elements_gui(pdf_filename, story_elements):
    """Generates a PDF document, logging progress/errors to GUI."""
    if not REPORTLAB_AVAILABLE:
        log_message("Error: Cannot generate PDF, reportlab library is missing.")
        show_error_gui(
            "PDF Error",
            "Cannot generate PDF because the 'reportlab' library is not installed.\nPlease install it using: pip install reportlab",
        )
        return False # Indicate failure

    log_message(f"\nGenerating PDF: {pdf_filename}...")
    try:
        doc = SimpleDocTemplate(pdf_filename)
        styles = getSampleStyleSheet()

        # Define custom styles (same as CLI version)
        styles.add(
            ParagraphStyle(
                name="BookTitle",
                parent=styles["h1"],
                fontSize=24,
                alignment=TA_CENTER,
                spaceAfter=20,
                textColor=navy,
            )
        )
        styles.add(
            ParagraphStyle(
                name="HeaderInfo",
                parent=styles["Normal"],
                fontSize=10,
                textColor=gray,
                alignment=TA_LEFT,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="SectionTitle",
                parent=styles["h2"],
                fontSize=16,
                alignment=TA_LEFT,
                spaceBefore=12,
                spaceAfter=8,
                textColor=navy,
            )
        )
        styles.add(
            ParagraphStyle(
                name="ChapterTitle",
                parent=styles["h2"],
                fontSize=18,
                alignment=TA_CENTER,
                spaceBefore=20,
                spaceAfter=10,
            )
        )
        styles.add(
            ParagraphStyle(
                name="OutlineChapter",
                parent=styles["h3"],
                fontSize=12,
                alignment=TA_LEFT,
                spaceBefore=8,
                spaceAfter=4,
                textColor=black,
            )
        )
        styles.add(
            ParagraphStyle(
                name="OutlineSubChapter",
                parent=styles["h4"],
                fontSize=11,
                alignment=TA_LEFT,
                leftIndent=20,
                spaceBefore=4,
                spaceAfter=2,
                textColor=black,
            )
        )
        styles.add(
            ParagraphStyle(
                name="OutlineSummary",
                parent=styles["Normal"],
                fontSize=10,
                alignment=TA_JUSTIFY,
                leftIndent=20, # Indent summaries slightly
                spaceAfter=6,
                firstLineIndent=12,
            )
        )
        """styles.add(
            ParagraphStyle(
                name="BodyText",
                parent=styles["Normal"],
                fontSize=11,
                alignment=TA_JUSTIFY,
                spaceAfter=6,
                firstLineIndent=18, # Standard paragraph indent
            )
        )"""

        flowables = []

        for element_type, text_content in story_elements:
            text_content = text_content.replace(
                "\n", "<br/>"
            ) # Convert newlines for Paragraph
            if element_type == "book_title":
                flowables.append(Paragraph(text_content, styles["BookTitle"]))
            elif element_type == "header_info":
                flowables.append(
                    Paragraph(text_content, styles["HeaderInfo"])
                )
            elif element_type == "section_title":
                flowables.append(
                    Paragraph(text_content, styles["SectionTitle"])
                )
                flowables.append(Spacer(1, 0.1 * inch))
            elif element_type == "outline_content":
                current_style = styles["OutlineSummary"] # Default
                lines = text_content.split("<br/>")
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("Chapter:"):
                        current_style = styles["OutlineChapter"]
                    elif line.startswith("- Sub-Chapter:"):
                        current_style = styles["OutlineSubChapter"]
                    else:
                        current_style = styles["OutlineSummary"]
                    flowables.append(Paragraph(line, current_style))
                flowables.append(Spacer(1, 0.1 * inch))
            elif element_type == "chapter_header":
                flowables.append(PageBreak()) # Start each chapter on new page
                flowables.append(
                    Paragraph(text_content, styles["ChapterTitle"])
                )
                flowables.append(Spacer(1, 0.1 * inch))
            elif element_type == "chapter_content":
                paragraphs = text_content.split("<br/><br/>")
                for para in paragraphs:
                    if para.strip():
                        flowables.append(Paragraph(para, styles["BodyText"]))
                flowables.append(Spacer(1, 0.1 * inch))
            else:
                flowables.append(Paragraph(text_content, styles["Normal"]))

        doc.build(flowables)
        log_message(f"PDF generation complete: {pdf_filename}")
        return True # Indicate success

    except Exception as e:
        log_message(f"\n--- ERROR Generating PDF ---")
        log_message(f"File: {pdf_filename}")
        log_message(f"Error: {e}")
        log_message(traceback.format_exc())
        log_message("----------------------------")
        show_error_gui("PDF Generation Error", f"Failed to generate PDF:\n{e}")
        return False # Indicate failure


# --- Modified Original Functions ---

def split_string_into_chunks(input_string, chunk_length):
    """
    Split a long string into chunks of specified length,
    ensuring chunks break at word boundaries. (No changes needed)
    """
    if not input_string:
        return ""
    words = input_string.split()
    chunks = []
    current_chunk = []
    current_length = 0
    for word in words:
        word_len = len(word)
        potential_len = current_length + word_len + (
            1 if current_length > 0 else 0
        )
        if potential_len > chunk_length:
            if current_chunk: # Don't add empty chunks
                chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_length = word_len
            # Handle case where a single word is longer than chunk_length
            if word_len > chunk_length:
                chunks.append(word) # Add the long word as its own chunk
                current_chunk = []
                current_length = 0
        else:
            current_chunk.append(word)
            current_length = potential_len
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return "\n".join(chunks)


def writeToFile(filename, content):
    """Appends content to a file. Logs errors to GUI."""
    try:
        # Use 'a' mode for appending
        with open(filename, "a", encoding="utf-8") as f:
            f.write(content)
    except IOError as e:
        log_message(f"Error writing to file {filename}: {e}")
        log_message("Exiting due to file write error.")
        raise IOError(
            f"File write error on {filename}"
        ) # Raise exception to be caught by generation logic


def removeBrackets(text=""):
    """Removes '<' and '>' characters from a string. Logs warnings to GUI."""
    if not isinstance(text, str):
        log_message(
            f"Warning: removeBrackets received non-string input: {type(text)}"
        )
        return text # Return input as-is if not a string
    text = text.replace(">", "")
    text = text.replace("<", "")
    return text


# to generate a prompt (Use log_message for internal errors)
def generatePrompt(
    option,
    bookName,
    bookGenre,
    numberOfChapters,
    bookBrief,
    combinedChapterDetails,
    wordsPerChapter,
    wordsPerSubchapter,
    bookOutline,
    numberOfSubchapters,
    lastGeneratedSubchapter_Full, # Pass more context
    lastGeneratedChapter_Full, # Pass more context
    currentChapter,
    currentSubchapter,
    character_bios="",
    world_notes="", # NEW Optional context
    start_chapter_chunk=None,
    end_chapter_chunk=None,
    previous_outline_context="",
):
    """Generates prompts for the AI.
    1 = outline (full or chunk), 2 = chapter gen, 3 = sub-chapter gen.
    """
    # Ensure numeric types where expected, handle potential GUI input issues
    try:
        wordsPerChapter_int = int(wordsPerChapter) if wordsPerChapter else 0
    except (ValueError, TypeError):
        log_message(
            f"Warning: Invalid 'wordsPerChapter' value ('{wordsPerChapter}'). Using 0."
        )
        wordsPerChapter_int = 0
    try:
        wordsPerSubchapter_int = (
            int(wordsPerSubchapter) if wordsPerSubchapter else 0
        )
    except (ValueError, TypeError):
        log_message(
            f"Warning: Invalid 'wordsPerSubchapter' value ('{wordsPerSubchapter}'). Using 0."
        )
        wordsPerSubchapter_int = 0

    bookGenre_str = (
        ", ".join(bookGenre) if isinstance(bookGenre, list) else bookGenre
    )

    # --- Context Snippets (Use more context) ---
    MAX_CONTEXT_CHARS = 2000 # Increased context length
    prev_chap_context = (
        f"... {lastGeneratedChapter_Full[-MAX_CONTEXT_CHARS:]}"
        if lastGeneratedChapter_Full
        else "N/A - This is the first chapter."
    )
    prev_sub_context = (
        f"... {lastGeneratedSubchapter_Full[-MAX_CONTEXT_CHARS:]}"
        if lastGeneratedSubchapter_Full
        else "N/A - This is the first sub-chapter of the chapter or book."
    )

    # --- Optional Context Inclusion ---
    character_context = (
        f"\n- Character Notes: {character_bios}" if character_bios else ""
    )
    world_context = (
        f"\n- World/Setting Notes: {world_notes}" if world_notes else ""
    )

    if option == 1: # outline
        sub_needed_text = "Yes" if numberOfSubchapters > 0 else "No"
        sub_instruction = (
            f"Generate EXACTLY {numberOfSubchapters} sub-chapters per chapter."
            if numberOfSubchapters > 0
            else "DO NOT generate sub-chapters."
        )

        is_chunked_request = (
            start_chapter_chunk is not None and end_chapter_chunk is not None
        )
        if is_chunked_request:
            task_description = f"You are generating PART of a 'Book Outline' for chapters {start_chapter_chunk} through {end_chapter_chunk}."
            chapter_range_instruction = f"ONLY generate the outline details for chapters {start_chapter_chunk} to {end_chapter_chunk} inclusive."
            context_instruction = (
                f"Ensure the summaries for these chapters flow logically from the previous part of the outline and contribute to the overall plot arc. The end of the previous section is:\n\"... {previous_outline_context[-1000:]}\""
                if previous_outline_context
                else "This is the first chunk of the outline."
            )
        else:
            task_description = "You are an AI that is made for generating a complete 'Book Outline' based on simple information given about a book."
            chapter_range_instruction = (
                f"Generate the outline for ALL {numberOfChapters} chapters."
            )
            context_instruction = "The whole book outline should form a coherent narrative structure. Each chapter summary must advance the plot, develop characters, or build the world, contributing logically to the overall story arc."

        # (Prompt content remains the same as original script)
        return f"""
{task_description}
You will generate a detailed 100-150 word summary for each chapter (and sub-chapter if needed).
Sub-chapters (if needed) break down the chapter's events into manageable narrative segments.
{sub_instruction} ONLY IF sub-chapters are needed as specified below.
You will go chapter by chapter, and if needed, sub-chapter by sub-chapter inside each chapter.
{chapter_range_instruction}

MAKE SURE summaries are detailed, outlining key events, character actions/reactions, important dialogue points, setting changes, and significant reveals or turning points.
MAKE SURE to describe the *purpose* of the chapter/sub-chapter within the larger narrative (e.g., introduce conflict, develop relationship, reveal clue, raise stakes).
MAKE SURE chapters and sub-chapters transition logically, building upon previous events and setting up future ones.
{context_instruction}
MAKE SURE the generated outline aligns with the Book Brief, Genre, and specific Chapter Details provided.

ONLY output in this format below: DO NOT OUTPUT THE ARROW BRACKETS.
<
For chapters:
Chapter: [chapter_number]: [chapter_name]
[chapter_summary]
>

DO NOT OUTPUT THE ARROW BRACKETS.

For sub-chapters (inside a chapter, ONLY IF NEEDED): DO NOT OUTPUT THE ARROW BRACKETS.
<
- Sub-Chapter: [sub-chapter_number]: [sub-chapter_name]
[sub-chapter_summary]
>

DO NOT OUTPUT THE ARROW BRACKETS.

ONLY output using plain text.
DO NOT use any markdown formatting.
DO NOT output any external words or anything besides the formatting.
DO NOT repeat any chapters/sub-chapters.

I will now provide all the information/context about the book below:
- Book Name: "{bookName}"
- Book Genre: "{bookGenre_str}"
- Total Number of Chapters in Book: "{numberOfChapters}"
- Chapter Details Provided: "{combinedChapterDetails}"
- Plot Summary: "{bookBrief}"
- Number of sub-chapters per chapter: "{numberOfSubchapters}"
- Are sub-chapters Needed?: "{sub_needed_text}"
{character_context}
{world_context}

You MUST follow all guidelines and instructions and generate the most coherent and compelling book outline {f'for chapters {start_chapter_chunk}-{end_chapter_chunk}' if is_chunked_request else 'for the entire book'}. DO NOT OUTPUT THE ARROW BRACKETS.
"""

    elif option == 2 or option == 3:
        unit_type = "chapter" if option == 2 else "sub-chapter"
        current_unit_num = (
            currentChapter
            if option == 2
            else f"{currentChapter}-{currentSubchapter}"
        )
        target_words = wordsPerChapter_int if option == 2 else wordsPerSubchapter_int
        min_target_words = int(target_words * 0.85)
        last_content_context = (
            prev_chap_context if option == 2 else prev_sub_context
        )

        relevant_outline = f"[ERROR: Could not extract outline for {unit_type} {current_unit_num}]"
        try:
            outline_lines = bookOutline.splitlines()
            search_str_chap = f"Chapter: {currentChapter}:"
            search_str_sub = (
                f"- Sub-Chapter: {currentSubchapter}:" if option == 3 else None
            )
            in_correct_section = False
            section_lines = []
            for line in outline_lines:
                stripped_line = line.strip()
                if option == 2: # Chapter
                    if stripped_line.startswith(search_str_chap):
                        in_correct_section = True
                        section_lines.append(line)
                        continue
                    elif in_correct_section and (
                        stripped_line.startswith("Chapter:")
                        or not stripped_line
                    ):
                        break
                elif option == 3: # Sub-chapter
                    if stripped_line.startswith(search_str_sub):
                        in_correct_section = True
                        section_lines.append(line)
                        continue
                    elif in_correct_section and (
                        stripped_line.startswith("- Sub-Chapter:")
                        or stripped_line.startswith("Chapter:")
                        or not stripped_line
                    ):
                        break
                if in_correct_section and stripped_line:
                    section_lines.append(line)

            if section_lines:
                relevant_outline = "\n".join(section_lines)
            else:
                log_message(
                    f"Warning: Could not parse specific outline for {unit_type} {current_unit_num} from G_bookOutline."
                )

        except Exception as e:
            log_message(f"Error parsing outline for prompt: {e}")

        storytelling_guidelines = f"""
WRITING STYLE & QUALITY GUIDELINES:
*   **Show, Don't Tell:** Instead of stating emotions or facts, describe the actions, dialogue, sensations, and internal thoughts that reveal them.
*   **Sensory Details:** Engage the reader by incorporating vivid details related to sight, sound, smell, touch, and taste relevant to the scene.
*   **Character Depth:** Explore the character(s)' motivations, internal thoughts, feelings, and reactions to events. Maintain consistent character voices.
*   **Pacing:** Vary sentence length and paragraph structure to control the pace. Use shorter sentences for action, longer ones for description or reflection.
*   **Atmosphere & Tone:** Establish and maintain the appropriate mood (e.g., suspenseful, melancholic, exciting) using descriptive language and word choice consistent with the genre ({bookGenre_str}).
*   **Engaging Narrative:** Write compelling prose that draws the reader in. Use strong verbs and avoid clichés.
*   **Dialogue:** Craft natural-sounding dialogue that reveals character personality, relationships, and advances the plot. Avoid exposition dumps in dialogue.
*   **Smooth Transitions:** Ensure logical flow between paragraphs and scenes.
*   **Expand on Outline:** Use the provided outline section as a framework, but flesh it out with rich detail, character interactions, and immersive descriptions. Do not simply list the outline points. Bring the events to life.
"""

        # (Prompt content remains the same as original script)
        return f"""
You are an AI tasked with writing the content for {unit_type} {current_unit_num} of the book "{bookName}".
Your writing should be engaging, descriptive, and aligned with the {bookGenre_str} genre.

{storytelling_guidelines}

CONTENT REQUIREMENTS:
*   Generate APPROXIMATELY {target_words} words (+-15% is acceptable). Minimum should be around {min_target_words} words.
*   The story MUST expand upon the provided Book Outline section for {unit_type} {current_unit_num}. Include all key events, but develop them naturally within the narrative.
*   ONLY generate content for {unit_type} {current_unit_num}.
*   Maintain narrative continuity, flowing smoothly from the previous content provided.
*   Stay focused on the events and themes relevant to this specific {unit_type}.

STRICT OUTPUT FORMAT:
*   ONLY output the raw text content for {unit_type} {current_unit_num}.
*   DO NOT include headers like "Chapter: ..." or "Sub-Chapter: ...".
*   DO NOT use markdown formatting.
*   Write in coherent paragraphs.

CONTEXT:
- Book Name: "{bookName}"
- Book Genre: "{bookGenre_str}"
- Total Number of Chapters: "{numberOfChapters}"
- Plot Summary: "{bookBrief}"
- Specific Chapter Details (User Input): "{combinedChapterDetails}"
- Book Outline (Relevant Section for {unit_type} {current_unit_num}): "{relevant_outline}"
- Target Words for this {unit_type}: "{target_words}"
{character_context}
{world_context}
- Previous Content End Snippet (for flow): "{last_content_context}"

Generate the content for {unit_type} {current_unit_num} now, following all instructions and focusing on high-quality, immersive storytelling.
"""
    else:
        log_message(
            f"Error: Incorrect option number '{option}' passed to generatePrompt."
        )
        return "Error: Incorrect option number"


def getResponse(apiKey, prompt, max_tokens=8192):
    """Make API call to Gemini. Logs progress/errors to GUI."""
    log_message(f"  Making API call (max_tokens={max_tokens})...")
    # Use 2.0 flash latest stable
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent?key={apiKey}"

    headers = {"Content-Type": "application/json"}

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": max_tokens,
            "topP": 0.95,
            "topK": 40,
        },
        "safetySettings": [ # Keep relaxed safety settings
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE",
            },
        ],
    }

    try:
        response = r.post(url, headers=headers, json=payload, timeout=300)

        try:
            data = response.json()
        except json.JSONDecodeError:
            log_message(
                f"API Error: Status Code {response.status_code}, Non-JSON Response:"
            )
            log_message(response.text[:500]) # Log first 500 chars
            if response.status_code == 429:
                log_message("Quota limit likely reached (Status 429).")
                return QUOTA_EXCEEDED_ERROR_STRING
            return f"API Error: {response.status_code} - Non-JSON Response"

        if "error" in data:
            error_info = data["error"]
            status_code = error_info.get("code", response.status_code)
            error_message = error_info.get("message", "Unknown error structure")
            log_message(f"API Error: {status_code} - {error_message}")
            if (
                status_code == 429
                or "quota" in error_message.lower()
                or "rate limit" in error_message.lower()
            ):
                log_message("Quota limit likely reached.")
                return QUOTA_EXCEEDED_ERROR_STRING
            return f"API Error: {status_code} - {error_message}"

        if response.status_code == 200:
            try:
                candidate = data.get("candidates", [{}])[0]
                finish_reason = candidate.get("finishReason", "UNKNOWN")

                if finish_reason not in ["STOP", "MAX_TOKENS"]:
                    safety_ratings = candidate.get("safetyRatings", [])
                    log_message(
                        f"Warning: Generation finished with reason: {finish_reason}"
                    )
                    content = candidate.get("content", {})
                    parts = content.get("parts", [{}])
                    if parts and "text" in parts[0]:
                        message = parts[0]["text"]
                        log_message("  (Content might be partial or incomplete)")
                        return f"API Warning: Generation finished unexpectedly ({finish_reason}), content may be incomplete."
                    else:
                        if safety_ratings:
                            log_message("Safety Ratings:")
                            for rating in safety_ratings:
                                log_message(
                                    f"  - {rating['category']}: {rating['probability']}"
                                )
                        return f"API Error: Generation stopped ({finish_reason}) with no content."

                content = candidate.get("content", {})
                parts = content.get("parts", [{}])
                if parts and "text" in parts[0]:
                    message = parts[0]["text"]
                    if finish_reason == "MAX_TOKENS":
                        log_message(
                            "Warning: Max output tokens reached. Content might be truncated."
                        )
                    log_message("  API call successful.")
                    return message
                else:
                    log_message(
                        "API Error: Response successful, but no text content found."
                    )
                    log_message(f"Response data: {json.dumps(data, indent=2)}")
                    safety_ratings = candidate.get("safetyRatings", [])
                    if safety_ratings:
                        log_message("Safety Ratings:")
                        for rating in safety_ratings:
                            log_message(
                                f"  - {rating['category']}: {rating['probability']}"
                            )
                    return "API Error: No text content found in response (possibly blocked by safety filter)"

            except (KeyError, IndexError, TypeError) as e:
                log_message(f"Error parsing successful response: {e}")
                log_message(f"Response data: {json.dumps(data, indent=2)}")
                return f"Error parsing response: {e}"
        else:
            if response.status_code == 429:
                log_message("Quota limit likely reached (Status 429).")
                return QUOTA_EXCEEDED_ERROR_STRING
            error_detail = data.get("error", {}).get(
                "message", f"Status Code {response.status_code}"
            )
            log_message(f"API Error: {error_detail}")
            log_message(f"Response data: {json.dumps(data, indent=2)}")
            return f"API Error: {error_detail}"

    except r.exceptions.Timeout:
        log_message(f"Request timed out after {300} seconds.")
        return "API Error: Request Timeout"
    except r.exceptions.RequestException as e:
        log_message(f"Request failed: {e}")
        return f"Request failed: {e}"
    except Exception as e:
        log_message(f"An unexpected error occurred in getResponse: {e}")
        log_message(traceback.format_exc())
        return f"Unexpected Error: {e}"


# --- Helper for Quota Handling (GUI Version - No changes needed) ---
def handle_quota_error_gui():
    """Prompts user for a new API key via GUI and updates state."""
    log_message("\n--- API Quota Limit Reached ---")
    log_message("The current API key has likely reached its usage limit.")
    while True:
        # Use CTkInputDialog via process_queue
        new_key = ask_string_gui(
            "Quota Limit Reached",
            "Please enter a new Google AI API key (or press Cancel):",
        )
        if new_key is None or not new_key.strip():
            log_message("No new key provided. Aborting generation.")
            return False
        new_key = new_key.strip()
        if len(new_key) > 30 and "AI" in new_key:
            gen_state["apiKey"] = new_key
            log_message("API Key updated. Retrying the last request...")
            sleep(1)
            return True
        else:
            show_error_gui(
                "Invalid Key", "Invalid API key format. Please try again."
            )


# --- Global Variables (User Input - To be populated by GUI) ---
input_data = {}

# --- Global Variables (Derived/Runtime - Used within generation thread) ---
gen_state = {
    "numberOfSubchapters": 0,
    "wordsPerSubchapter": 0.0,
    "combinedChapterDetails": "",
    "totalWords": 0,
    "currentChapter": 0,
    "currentSubChapter": 0,
    "lastGeneratedChapter_Full": "",
    "lastGeneratedSubchapter_Full": "",
    "totalGeneratedWords": 0,
    "waitTime": 5,
    "regenOnLowWords": False,
    "txt_full_path": "", # Renamed from full_path
    "pdf_full_path": "", # Added for PDF
    "total_outline_items": 0,
    "G_bookOutline": "",
    "apiKey": "",
    "outputFormat": [], # Added for output choice
    "pdf_story_elements": [], # Added for PDF content
}


# --- Main Generation Logic (to be run in a thread) ---
def run_generation_logic(inputs):
    """The core generation process, adapted from main()."""
    # Clear previous PDF elements if any
    gen_state["pdf_story_elements"] = []

    # Local copies or references for clarity
    I_bookName = inputs["bookName"]
    I_bookGenre = inputs["bookGenre"]
    I_wordsPerChapter = inputs["wordsPerChapter"]
    I_numberOfChapters = inputs["numberOfChapters"]
    I_chapterDetails_list = inputs["chapterDetails_list"] # Use the parsed list
    I_bookBrief = inputs["bookBrief"]
    I_apiKey = inputs["apiKey"]
    I_apiLevel = inputs["apiLevel"]
    I_characterBios = inputs["characterBios"]
    I_worldNotes = inputs["worldNotes"]
    regenOnLowWords = inputs["regenOnLowWords"]
    txt_full_path = inputs["txt_full_path"] # Use specific path
    pdf_full_path = inputs["pdf_full_path"] # Use specific path
    outputFormat = inputs["outputFormat"] # Get output format choice

    # --- Initialize generation state ---
    gen_state["numberOfSubchapters"] = 0
    gen_state["wordsPerSubchapter"] = 0.0
    gen_state["combinedChapterDetails"] = " | ".join(
        [
            f'Chapter {i+1} Outline: "{detail}"'
            for i, detail in enumerate(I_chapterDetails_list)
        ]
    )
    gen_state["totalWords"] = 0
    gen_state["currentChapter"] = 0
    gen_state["currentSubChapter"] = 0
    gen_state["lastGeneratedChapter_Full"] = ""
    gen_state["lastGeneratedSubchapter_Full"] = ""
    gen_state["totalGeneratedWords"] = 0
    gen_state["waitTime"] = 5 if I_apiLevel == 0 else 0.5
    gen_state["regenOnLowWords"] = regenOnLowWords
    gen_state["txt_full_path"] = txt_full_path # Store in state
    gen_state["pdf_full_path"] = pdf_full_path # Store in state
    gen_state["total_outline_items"] = 0
    gen_state["G_bookOutline"] = ""
    gen_state["apiKey"] = I_apiKey # Initial API key
    gen_state["outputFormat"] = outputFormat # Store in state

    log_message("----- Generation Thread Started -----")

    try:
        # --- Calculate dependent variables ---
        gen_state["totalWords"] = I_wordsPerChapter * I_numberOfChapters
        SUBCHAPTER_THRESHOLD = 1500
        TARGET_SUBCHAPTER_WORDS = 500
        if I_wordsPerChapter > SUBCHAPTER_THRESHOLD:
            gen_state["numberOfSubchapters"] = ceil(
                I_wordsPerChapter / TARGET_SUBCHAPTER_WORDS
            )
            gen_state["numberOfSubchapters"] = max(
                3, gen_state["numberOfSubchapters"]
            ) # Ensure at least 3 if splitting
            gen_state["wordsPerSubchapter"] = ceil(
                I_wordsPerChapter / gen_state["numberOfSubchapters"]
            )
            log_message(
                f"\nChapters > {SUBCHAPTER_THRESHOLD} words, split into {gen_state['numberOfSubchapters']} sub-chapters (~{int(gen_state['wordsPerSubchapter'])} words each)."
            )
        else:
            gen_state["numberOfSubchapters"] = 0
            gen_state["wordsPerSubchapter"] = 0

        if gen_state["numberOfSubchapters"] > 0:
            gen_state["total_outline_items"] = (
                I_numberOfChapters * gen_state["numberOfSubchapters"]
            )
        else:
            gen_state["total_outline_items"] = I_numberOfChapters
        log_message(
            f"Total outline items to generate: {gen_state['total_outline_items']}"
        )

        # --- Adjust Word Count Multiplier ---
        word_multiplier = 1.8
        wordsPerSubchapter_gen = (
            gen_state["wordsPerSubchapter"] * word_multiplier
            if gen_state["wordsPerSubchapter"] > 0
            else 0
        )
        wordsPerChapter_gen = I_wordsPerChapter * word_multiplier
        log_message(
            f"Adjusted Prompt Target Words/Chapter: ~{int(wordsPerChapter_gen)}"
        )
        if gen_state["numberOfSubchapters"] > 0:
            log_message(
                f"Adjusted Prompt Target Words/Sub-Chapter: ~{int(wordsPerSubchapter_gen)}"
            )

        # ----- Step 2. Generation -----
        log_message("\n-----Step 2. Generation-----")
        log_message(" - Generating book outline and content...")
        log_message(" - This may take a significant amount of time.")

        # --- Generate Book Outline ---
        log_message("\nGenerating Book Outline...")
        G_bookOutline = "" # Local to this function scope now
        outline_generated_successfully = False
        outline_regeneration_requested = False

        while not outline_generated_successfully or outline_regeneration_requested:
            outline_regeneration_requested = False
            G_bookOutline = "" # Reset content for this attempt/regeneration
            full_outline_parts = []
            previous_outline_context = ""
            outline_generation_failed = False

            if gen_state["total_outline_items"] > OUTLINE_CHUNK_THRESHOLD:
                log_message(
                    f"Outline has {gen_state['total_outline_items']} items, > {OUTLINE_CHUNK_THRESHOLD}. Generating in chunks..."
                )
                num_chunks = ceil(I_numberOfChapters / CHAPTERS_PER_OUTLINE_CHUNK)
                log_message(f"Total Chunks: {num_chunks}")

                for chunk_index in range(num_chunks):
                    start_chap = chunk_index * CHAPTERS_PER_OUTLINE_CHUNK + 1
                    end_chap = min(
                        (chunk_index + 1) * CHAPTERS_PER_OUTLINE_CHUNK,
                        I_numberOfChapters,
                    )
                    log_message(
                        f"\nGenerating Outline Chunk {chunk_index + 1}/{num_chunks} (Chapters {start_chap}-{end_chap})..."
                    )

                    chunk_generated_successfully = False
                    attempt = 1
                    while (
                        attempt <= MAX_GENERATION_ATTEMPTS
                        and not chunk_generated_successfully
                    ):
                        log_message(
                            f"  Attempt {attempt}/{MAX_GENERATION_ATTEMPTS}..."
                        )
                        outline_prompt = generatePrompt(
                            1,
                            I_bookName,
                            I_bookGenre,
                            I_numberOfChapters,
                            I_bookBrief,
                            gen_state["combinedChapterDetails"],
                            wordsPerChapter_gen,
                            wordsPerSubchapter_gen,
                            "",
                            gen_state["numberOfSubchapters"],
                            "",
                            "",
                            0,
                            0,
                            character_bios=I_characterBios,
                            world_notes=I_worldNotes,
                            start_chapter_chunk=start_chap,
                            end_chapter_chunk=end_chap,
                            previous_outline_context=previous_outline_context,
                        )

                        response = getResponse(
                            gen_state["apiKey"], outline_prompt, max_tokens=6144
                        )

                        if response == QUOTA_EXCEEDED_ERROR_STRING:
                            if not handle_quota_error_gui():
                                outline_generation_failed = True
                                break
                            continue
                        elif (
                            response.startswith("API Error:")
                            or response.startswith("Error parsing")
                            or response.startswith("Request failed:")
                            or response.startswith("Unexpected Error:")
                            or response.startswith("API Warning:")
                        ):
                            log_message(
                                f"  Error/Warning generating outline chunk {chunk_index + 1} (Attempt {attempt}): {response}"
                            )
                            if attempt == MAX_GENERATION_ATTEMPTS:
                                log_message(
                                    f"  Max attempts reached for chunk {chunk_index + 1}."
                                )
                                outline_generation_failed = True
                                break
                            else:
                                log_message(
                                    f"  Waiting {gen_state['waitTime']*2}s before retry..."
                                )
                                sleep(gen_state["waitTime"] * 2)
                            attempt += 1
                            continue

                        chunk_text = removeBrackets(response)
                        full_outline_parts.append(chunk_text)
                        previous_outline_context = chunk_text
                        log_message(
                            f"  Outline Chunk {chunk_index + 1} generated successfully."
                        )
                        chunk_generated_successfully = True
                        sleep(gen_state["waitTime"])
                    if outline_generation_failed or not chunk_generated_successfully:
                        break
                if not outline_generation_failed:
                    G_bookOutline = "\n\n".join(full_outline_parts)
                    outline_generated_successfully = True
                    log_message("Full Outline Assembled!")
            else:
                # --- Single Call Outline Generation ---
                log_message("Generating outline in a single call...")
                attempt = 1
                single_call_success = False
                while (
                    attempt <= MAX_GENERATION_ATTEMPTS
                    and not single_call_success
                ):
                    log_message(
                        f"  Attempt {attempt}/{MAX_GENERATION_ATTEMPTS}..."
                    )
                    outline_prompt = generatePrompt(
                        1,
                        I_bookName,
                        I_bookGenre,
                        I_numberOfChapters,
                        I_bookBrief,
                        gen_state["combinedChapterDetails"],
                        wordsPerChapter_gen,
                        wordsPerSubchapter_gen,
                        "",
                        gen_state["numberOfSubchapters"],
                        "",
                        "",
                        0,
                        0,
                        character_bios=I_characterBios,
                        world_notes=I_worldNotes,
                    )

                    response = getResponse(
                        gen_state["apiKey"], outline_prompt, max_tokens=8192
                    )

                    if response == QUOTA_EXCEEDED_ERROR_STRING:
                        if not handle_quota_error_gui():
                            outline_generation_failed = True
                            break
                        continue
                    elif (
                        response.startswith("API Error:")
                        or response.startswith("Error parsing")
                        or response.startswith("Request failed:")
                        or response.startswith("Unexpected Error:")
                        or response.startswith("API Warning:")
                    ):
                        log_message(
                            f"  Error/Warning during single outline generation (Attempt {attempt}): {response}"
                        )
                        if attempt == MAX_GENERATION_ATTEMPTS:
                            log_message(
                                f"  Max attempts reached for single outline generation."
                            )
                            outline_generation_failed = True
                            break
                        else:
                            log_message(
                                f"  Waiting {gen_state['waitTime']*2}s before retry..."
                            )
                            sleep(gen_state["waitTime"] * 2)
                        attempt += 1
                        continue

                    G_bookOutline = removeBrackets(response)
                    single_call_success = True
                    outline_generated_successfully = True
                    log_message("Book Outline Generation Complete!")
                    sleep(gen_state["waitTime"])

            if outline_generation_failed:
                if not ask_question_gui(
                    "Outline Failed",
                    "Outline generation failed. Retry the entire outline generation?",
                ):
                    raise RuntimeError(
                        "Outline generation failed and user chose not to retry."
                    )
                else:
                    log_message("Retrying outline generation...")
                    outline_generated_successfully = False
                    continue

            if outline_generated_successfully:
                log_message("\n--- Generated Outline (Preview) ---")
                log_message(f"{G_bookOutline[:1000]}...") # Log preview
                log_message("--- End Outline Preview ---\n")

                if ask_question_gui(
                    "Review Outline", "Regenerate outline if not satisfactory?"
                ):
                    log_message("Regenerating Book Outline...")
                    outline_regeneration_requested = True
                    outline_generated_successfully = False
                else:
                    log_message("Keeping the generated outline.")
                    break

        gen_state["G_bookOutline"] = G_bookOutline

        # --- Prepare Header Info for Files ---
        header_lines = []
        header_lines.append(f"Book Title: {I_bookName}")
        header_lines.append(f"Genre: {', '.join(I_bookGenre)}")
        header_lines.append(f"Target Chapters: {I_numberOfChapters}")
        header_lines.append(
            f"Target Words/Chapter (Prompt): ~{int(wordsPerChapter_gen)}"
        )
        header_lines.append(
            f"Sub-Chapters/Chapter: {gen_state['numberOfSubchapters']}"
        )
        if gen_state["numberOfSubchapters"] > 0:
            header_lines.append(
                f"Target Words/Sub-Chapter (Prompt): ~{int(wordsPerSubchapter_gen)}"
            )
        if I_characterBios:
            header_lines.append("\n----- CHARACTER NOTES -----")
            header_lines.append(I_characterBios)
        if I_worldNotes:
            header_lines.append("\n----- WORLD NOTES -----")
            header_lines.append(I_worldNotes)

        # --- Add Header and Outline to PDF Elements ---
        if "pdf" in outputFormat:
            gen_state["pdf_story_elements"].append(("book_title", I_bookName))
            for line in header_lines[1:]:
                if line.strip():
                    if line.startswith("-----"):
                        gen_state["pdf_story_elements"].append(
                            ("section_title", line.strip())
                        )
                    else:
                        gen_state["pdf_story_elements"].append(
                            ("header_info", line)
                        )
            gen_state["pdf_story_elements"].append(
                ("section_title", "----- BOOK OUTLINE -----")
            )
            gen_state["pdf_story_elements"].append(
                ("outline_content", gen_state["G_bookOutline"])
            )
            gen_state["pdf_story_elements"].append(
                ("section_title", "----- BOOK CONTENT -----")
            )

        # --- Write Header Info and Outline to TXT File ---
        if "txt" in outputFormat:
            log_message(f"Writing header and final outline to {txt_full_path}...")
            initial_content = "\n".join(header_lines)
            initial_content += "\n\n----- BOOK OUTLINE -----\n"
            initial_content += gen_state["G_bookOutline"]
            initial_content += "\n\n----- BOOK CONTENT -----\n"
            try:
                with open(txt_full_path, "w", encoding="utf-8") as f:
                    f.write(initial_content)
            except IOError as e:
                log_message(
                    f"FATAL ERROR: Could not write initial header to file {txt_full_path}: {e}"
                )
                raise

        # --- Generate Book Contents ---
        log_message("\nStarting Chapter/Sub-Chapter Generation...")
        gen_state["totalGeneratedWords"] = 0
        gen_state["lastGeneratedChapter_Full"] = ""

        for chap_num in range(1, I_numberOfChapters + 1):
            gen_state["currentChapter"] = chap_num
            chapter_title_text = f"Chapter: {gen_state['currentChapter']}"
            chapter_header_txt = f"\n\n---------- Chapter: {gen_state['currentChapter']} ----------\n\n"
            log_message(
                f"\n----- Generating Chapter: {gen_state['currentChapter']}/{I_numberOfChapters} -----"
            )

            # Write TXT header
            if "txt" in outputFormat:
                writeToFile(txt_full_path, chapter_header_txt)
            # Add PDF header element
            if "pdf" in outputFormat:
                gen_state["pdf_story_elements"].append(
                    ("chapter_header", chapter_title_text)
                )

            gen_state["lastGeneratedSubchapter_Full"] = ""
            current_chapter_content_parts = []
            target_word_count_tolerance = 0.20

            if gen_state["numberOfSubchapters"] > 0:
                # --- Sub-Chapter Generation ---
                target_words_sub = int(wordsPerSubchapter_gen)
                min_words_sub = int(
                    target_words_sub * (1 - target_word_count_tolerance)
                )

                for sub_chap_num in range(
                    1, gen_state["numberOfSubchapters"] + 1
                ):
                    gen_state["currentSubChapter"] = sub_chap_num
                    log_message(
                        f"  Generating Sub-Chapter: {gen_state['currentSubChapter']}/{gen_state['numberOfSubchapters']}..."
                    )
                    sub_chapter_generated_successfully = False
                    attempt = 1
                    while (
                        attempt <= MAX_GENERATION_ATTEMPTS
                        and not sub_chapter_generated_successfully
                    ):
                        log_message(
                            f"    Attempt {attempt}/{MAX_GENERATION_ATTEMPTS}..."
                        )
                        prompt = generatePrompt(
                            3,
                            I_bookName,
                            I_bookGenre,
                            I_numberOfChapters,
                            I_bookBrief,
                            gen_state["combinedChapterDetails"],
                            wordsPerChapter_gen,
                            wordsPerSubchapter_gen,
                            gen_state["G_bookOutline"],
                            gen_state["numberOfSubchapters"],
                            gen_state["lastGeneratedSubchapter_Full"],
                            gen_state["lastGeneratedChapter_Full"],
                            gen_state["currentChapter"],
                            gen_state["currentSubChapter"],
                            character_bios=I_characterBios,
                            world_notes=I_worldNotes,
                        )

                        response = getResponse(gen_state["apiKey"], prompt)

                        if response == QUOTA_EXCEEDED_ERROR_STRING:
                            if not handle_quota_error_gui():
                                raise RuntimeError(
                                    "Generation aborted by user during quota handling."
                                )
                            continue
                        elif (
                            response.startswith("API Error:")
                            or response.startswith("Error parsing")
                            or response.startswith("Request failed:")
                            or response.startswith("Unexpected Error:")
                            or response.startswith("API Warning:")
                        ):
                            log_message(
                                f"    Error/Warning generating sub-chapter {gen_state['currentChapter']}-{gen_state['currentSubChapter']} (Attempt {attempt}): {response}"
                            )
                            if attempt == MAX_GENERATION_ATTEMPTS:
                                log_message(
                                    f"    Max attempts reached. Skipping sub-chapter {gen_state['currentChapter']}-{gen_state['currentSubChapter']}."
                                )
                                error_msg = f"\n\n!! ERROR: SUB-CHAPTER {gen_state['currentChapter']}-{gen_state['currentSubChapter']} !!\n{response}\n"
                                if "txt" in outputFormat:
                                    writeToFile(txt_full_path, error_msg)
                                if "pdf" in outputFormat:
                                    gen_state["pdf_story_elements"].append(
                                        ("chapter_content", error_msg)
                                    )
                                break
                            else:
                                log_message(
                                    f"    Waiting {gen_state['waitTime']*2}s before retry..."
                                )
                                sleep(gen_state["waitTime"] * 2)
                            attempt += 1
                            continue

                        generated_text = response
                        word_count = len(generated_text.split())
                        log_message(
                            f"    Sub-Chapter {gen_state['currentChapter']}-{gen_state['currentSubChapter']} (Attempt {attempt}) generated: ~{word_count} words."
                        )

                        if (
                            gen_state["regenOnLowWords"]
                            and word_count < min_words_sub
                        ):
                            if attempt < MAX_GENERATION_ATTEMPTS:
                                log_message(
                                    f"    Word count ({word_count}) < min ({min_words_sub}). Regenerating..."
                                )
                                sleep(gen_state["waitTime"])
                                attempt += 1
                                continue
                            else:
                                log_message(
                                    f"    Word count still low after {MAX_GENERATION_ATTEMPTS} attempts. Keeping."
                                )

                        gen_state["lastGeneratedSubchapter_Full"] = generated_text
                        current_chapter_content_parts.append(generated_text)
                        gen_state["totalGeneratedWords"] += word_count

                        # Write to TXT
                        if "txt" in outputFormat:
                            writeToFile(
                                txt_full_path,
                                split_string_into_chunks(generated_text, 150)
                                + "\n",
                            )
                        # Add to PDF elements
                        if "pdf" in outputFormat:
                            gen_state["pdf_story_elements"].append(
                                ("chapter_content", generated_text)
                            )

                        log_message(
                            f"  Sub-Chapter {gen_state['currentChapter']}-{gen_state['currentSubChapter']} finished."
                        )
                        sub_chapter_generated_successfully = True
                        sleep(gen_state["waitTime"])

                    if not sub_chapter_generated_successfully:
                        log_message(
                            f"  FAILED to generate Sub-Chapter {gen_state['currentChapter']}-{gen_state['currentSubChapter']} after max attempts."
                        )

                gen_state["lastGeneratedChapter_Full"] = "\n\n".join(
                    current_chapter_content_parts
                )

            else:
                # --- Full Chapter Generation (No Sub-Chapters) ---
                target_words_chap = int(wordsPerChapter_gen)
                min_words_chap = int(
                    target_words_chap * (1 - target_word_count_tolerance)
                )
                chapter_generated_successfully = False
                attempt = 1

                while (
                    attempt <= MAX_GENERATION_ATTEMPTS
                    and not chapter_generated_successfully
                ):
                    log_message(
                        f"  Generating Chapter {gen_state['currentChapter']} (Attempt {attempt}/{MAX_GENERATION_ATTEMPTS})..."
                    )
                    prompt = generatePrompt(
                        2,
                        I_bookName,
                        I_bookGenre,
                        I_numberOfChapters,
                        I_bookBrief,
                        gen_state["combinedChapterDetails"],
                        wordsPerChapter_gen,
                        0,
                        gen_state["G_bookOutline"],
                        0,
                        "",
                        gen_state["lastGeneratedChapter_Full"],
                        gen_state["currentChapter"],
                        0,
                        character_bios=I_characterBios,
                        world_notes=I_worldNotes,
                    )

                    response = getResponse(gen_state["apiKey"], prompt)

                    if response == QUOTA_EXCEEDED_ERROR_STRING:
                        if not handle_quota_error_gui():
                            raise RuntimeError(
                                "Generation aborted by user during quota handling."
                            )
                        continue
                    elif (
                        response.startswith("API Error:")
                        or response.startswith("Error parsing")
                        or response.startswith("Request failed:")
                        or response.startswith("Unexpected Error:")
                        or response.startswith("API Warning:")
                    ):
                        log_message(
                            f"  Error/Warning generating chapter {gen_state['currentChapter']} (Attempt {attempt}): {response}"
                        )
                        if attempt == MAX_GENERATION_ATTEMPTS:
                            log_message(
                                f"  Max attempts reached for chapter {gen_state['currentChapter']}. Skipping."
                            )
                            error_msg = f"\n\n!! ERROR: CHAPTER {gen_state['currentChapter']} !!\n{response}\n"
                            if "txt" in outputFormat:
                                writeToFile(txt_full_path, error_msg)
                            if "pdf" in outputFormat:
                                gen_state["pdf_story_elements"].append(
                                    ("chapter_content", error_msg)
                                )
                            break
                        else:
                            log_message(
                                f"  Waiting {gen_state['waitTime']*2}s before retry..."
                            )
                            sleep(gen_state["waitTime"] * 2)
                        attempt += 1
                        continue

                    generated_text = response
                    word_count = len(generated_text.split())
                    log_message(
                        f"  Chapter {gen_state['currentChapter']} (Attempt {attempt}) generated: ~{word_count} words."
                    )

                    if (
                        gen_state["regenOnLowWords"]
                        and word_count < min_words_chap
                    ):
                        if attempt < MAX_GENERATION_ATTEMPTS:
                            log_message(
                                f"  Word count ({word_count}) < min ({min_words_chap}). Regenerating..."
                            )
                            sleep(gen_state["waitTime"])
                            attempt += 1
                            continue
                        else:
                            log_message(
                                f"  Word count still low after {MAX_GENERATION_ATTEMPTS} attempts. Keeping."
                            )

                    gen_state["lastGeneratedChapter_Full"] = generated_text
                    gen_state["totalGeneratedWords"] += word_count

                    # Write to TXT
                    if "txt" in outputFormat:
                        writeToFile(
                            txt_full_path,
                            split_string_into_chunks(generated_text, 150) + "\n",
                        )
                    # Add to PDF elements
                    if "pdf" in outputFormat:
                        gen_state["pdf_story_elements"].append(
                            ("chapter_content", generated_text)
                        )

                    log_message(f"  Chapter {gen_state['currentChapter']} finished.")
                    chapter_generated_successfully = True
                    sleep(gen_state["waitTime"])

                if not chapter_generated_successfully:
                    log_message(
                        f"  FAILED to generate Chapter {gen_state['currentChapter']} after max attempts."
                    )

        # ----- Final PDF Generation -----
        pdf_success = True
        if "pdf" in outputFormat:
            pdf_success = generate_pdf_from_elements_gui(
                pdf_full_path, gen_state["pdf_story_elements"]
            )

        # ----- Final Summary -----
        log_message("\n----- Generation Complete! -----")
        log_message(f"Book '{I_bookName}' generation process finished.")
        log_message(
            f"Total approximate words generated: {gen_state['totalGeneratedWords']}"
        )
        final_message = "Book generation finished!\n\n"
        if "txt" in outputFormat:
            log_message(f"TXT output saved to: {txt_full_path}")
            final_message += f"TXT output saved to:\n{txt_full_path}\n\n"
        if "pdf" in outputFormat:
            if pdf_success:
                log_message(f"PDF output saved to: {pdf_full_path}")
                final_message += f"PDF output saved to:\n{pdf_full_path}\n\n"
            else:
                log_message("PDF generation failed. See log for details.")
                final_message += "PDF generation failed. See log for details.\n\n"

        log_message(
            "\nRecommendation: Please review the generated content for flow, consistency, and accuracy."
        )
        log_message("Manual editing will likely be required to refine the text.")
        show_info_gui("Success", final_message)

        gui_queue.put(("generation_finished", True))

    except KeyboardInterrupt: # Should not happen in thread, but good practice
        log_message("\n\n--- Generation Interrupted (KeyboardInterrupt) ---")
        if "txt" in gen_state.get("outputFormat", []):
            log_message(
                f"Partial TXT content may have been saved to '{gen_state.get('txt_full_path', 'N/A')}'."
            )
        gui_queue.put(("generation_finished", False))
    except Exception as e:
        log_message(
            "\n----- An Unexpected Error Occurred During Generation -----"
        )
        log_message(f"Error Type: {type(e).__name__}")
        log_message(f"Error Details: {e}")
        log_message("Traceback:")
        log_message(traceback.format_exc())
        log_message("----------------------------------------------------------")
        if "txt" in gen_state.get("outputFormat", []):
            log_message(
                f"Partial TXT content may have been saved to '{gen_state.get('txt_full_path', 'N/A')}'."
            )
        show_error_gui(
            "Generation Error", f"An error occurred: {e}\n\nCheck the log for details."
        )
        gui_queue.put(("generation_finished", False))


# ----- GUI Application Class ----- #

class BookGenApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Book Generator")
        # self.root.geometry("1000x800") # Suggest a wider starting size

        self.generation_thread = None
        self.input_widgets = [] # Keep track of widgets to disable/enable
        self.genre_checkboxes = {} # To store genre checkboxes {genre_name: checkbox_widget}
        self.genre_vars = {} # To store genre checkbox variables {genre_name: BooleanVar}

        # --- Theme ---
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        # --- Main Frame ---
        # Configure root window resizing
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        main_frame = ctk.CTkFrame(root, corner_radius=0)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # *** Configure TWO columns for input sections ***
        main_frame.grid_columnconfigure(
            0, weight=1, uniform="input_cols"
        ) # Left column
        main_frame.grid_columnconfigure(
            1, weight=1, uniform="input_cols"
        ) # Right column

        # *** Configure Rows for Layout ***
        # Input Section Rows (adjust weights as needed, 1 for expandable text areas)
        main_frame.grid_rowconfigure(0, weight=0) # Row 0: API/Chapter Labels
        main_frame.grid_rowconfigure(1, weight=0) # Row 1: API/Chapter Frames
        main_frame.grid_rowconfigure(2, weight=0) # Row 2: Book/Context Labels
        main_frame.grid_rowconfigure(
            3, weight=1
        ) # Row 3: Book/Context Frames (allow expansion)
        main_frame.grid_rowconfigure(4, weight=0) # Row 4: Options Label
        main_frame.grid_rowconfigure(5, weight=0) # Row 5: Options Frame
        # Bottom Rows
        main_frame.grid_rowconfigure(6, weight=0) # Row 6: Controls
        main_frame.grid_rowconfigure(7, weight=0) # Row 7: Log Label
        main_frame.grid_rowconfigure(
            8, weight=2
        ) # Row 8: Log Area (give more weight)

        # --- Column 0: Left Side Inputs ---

        # --- API Settings ---
        ctk.CTkLabel(
            main_frame, text="API Settings", font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(5, 2))
        api_frame = ctk.CTkFrame(main_frame)
        api_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        api_frame.grid_columnconfigure(1, weight=1) # Allow entry to expand

        ctk.CTkLabel(api_frame, text="Google AI API Key:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        self.api_key_var = StringVar()
        api_key_entry = ctk.CTkEntry(
            api_frame, textvariable=self.api_key_var, show="*"
        )
        api_key_entry.grid(row=0, column=1, sticky="ew", padx=10, pady=5)
        self.input_widgets.append(api_key_entry)

        ctk.CTkLabel(api_frame, text="API Tier:").grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )
        self.api_level_var = IntVar(value=0)
        api_tier_frame = ctk.CTkFrame(api_frame, fg_color="transparent")
        api_tier_frame.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        free_rb = ctk.CTkRadioButton(
            api_tier_frame,
            text="Free (Slow)",
            variable=self.api_level_var,
            value=0,
        )
        paid_rb = ctk.CTkRadioButton(
            api_tier_frame,
            text="Paid (Fast)",
            variable=self.api_level_var,
            value=1,
        )
        free_rb.grid(row=0, column=0, sticky="w", padx=5, pady=2)
        paid_rb.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        self.input_widgets.extend([free_rb, paid_rb])

        # --- Book Info ---
        ctk.CTkLabel(
            main_frame,
            text="Book Information",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=2, column=0, sticky="w", padx=10, pady=(15, 2))
        book_frame = ctk.CTkFrame(main_frame)
        # Make book frame stick to all sides within its cell (row 3, col 0)
        book_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=5)
        book_frame.grid_columnconfigure(1, weight=1)
        # Allow the row containing the brief text to expand vertically within book_frame
        book_frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(book_frame, text="Book Name:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        self.book_name_var = StringVar()
        book_name_entry = ctk.CTkEntry(
            book_frame, textvariable=self.book_name_var
        )
        book_name_entry.grid(row=0, column=1, sticky="ew", padx=10, pady=5)
        self.input_widgets.append(book_name_entry)

        ctk.CTkLabel(book_frame, text="Genre(s):").grid(
            row=1, column=0, sticky="nw", padx=10, pady=(10, 5)
        )
        self.available_genres = [
            "Fantasy",
            "Action/Adventure",
            "Literary Fiction",
            "Non-Fiction",
            "Dystopian",
            "Mystery",
            "Horror",
            "Thriller/Suspense",
            "Romance",
            "Childrens",
            "Memoir",
            "Sci-Fi",
            "Historical Fiction",
        ]
        genre_scroll_frame = ctk.CTkScrollableFrame(
            book_frame, label_text="", height=100
        )
        genre_scroll_frame.grid(row=1, column=1, sticky="ew", padx=10, pady=5)
        genre_scroll_frame.grid_columnconfigure(0, weight=1)
        self.input_widgets.append(genre_scroll_frame)

        for i, genre in enumerate(self.available_genres):
            var = BooleanVar()
            cb = ctk.CTkCheckBox(genre_scroll_frame, text=genre, variable=var)
            cb.grid(row=i, column=0, sticky="w", padx=5, pady=2)
            self.genre_checkboxes[genre] = cb
            self.genre_vars[genre] = var
            self.input_widgets.append(cb)

        ctk.CTkLabel(book_frame, text="Book Brief/Plot:").grid(
            row=2, column=0, sticky="nw", padx=10, pady=(10, 5)
        )
        self.brief_text = ctk.CTkTextbox(
            book_frame, wrap="word"
        ) # Removed fixed height, let it expand
        self.brief_text.grid(
            row=2, column=1, sticky="nsew", padx=10, pady=5
        ) # Use nsew
        self.input_widgets.append(self.brief_text)

        # --- Generation Options ---
        ctk.CTkLabel(
            main_frame,
            text="Generation Options",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=4, column=0, sticky="w", padx=10, pady=(15, 2))
        options_frame = ctk.CTkFrame(main_frame)
        options_frame.grid(row=5, column=0, sticky="ew", padx=10, pady=5)
        options_frame.grid_columnconfigure(0, weight=1) # Allow content to expand

        self.regen_low_words_var = BooleanVar(value=False)
        regen_check = ctk.CTkCheckBox(
            options_frame,
            text="Regenerate if word count is too low?",
            variable=self.regen_low_words_var,
        )
        regen_check.grid(row=0, column=0, sticky="w", padx=10, pady=5)
        self.input_widgets.append(regen_check)

        # --- Output Format Options ---
        ctk.CTkLabel(options_frame, text="Output Format:").grid(
            row=1, column=0, sticky="w", padx=10, pady=(10, 5)
        )
        output_format_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
        output_format_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

        self.output_txt_var = BooleanVar(value=True) # Default TXT to True
        self.output_pdf_var = BooleanVar(value=False)

        txt_check = ctk.CTkCheckBox(
            output_format_frame, text="TXT", variable=self.output_txt_var
        )
        pdf_check = ctk.CTkCheckBox(
            output_format_frame, text="PDF", variable=self.output_pdf_var
        )
        txt_check.grid(row=0, column=0, sticky="w", padx=5, pady=2)
        pdf_check.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        self.input_widgets.extend([txt_check, pdf_check])

        # --- Column 1: Right Side Inputs ---

        # --- Chapter Settings ---
        ctk.CTkLabel(
            main_frame,
            text="Chapter Settings",
            font=ctk.CTkFont(weight="bold"),
        ).grid(
            row=0, column=1, sticky="w", padx=10, pady=(5, 2)
        ) # Column 1
        chapter_frame = ctk.CTkFrame(main_frame)
        chapter_frame.grid(
            row=1, column=1, sticky="ew", padx=10, pady=5
        ) # Column 1
        chapter_frame.grid_columnconfigure(1, weight=1)
        # Allow chapter details textbox row to expand
        chapter_frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(chapter_frame, text="Number of Chapters:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        self.num_chapters_var = StringVar()
        num_chapters_entry = ctk.CTkEntry(
            chapter_frame, textvariable=self.num_chapters_var, width=120
        )
        num_chapters_entry.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        self.input_widgets.append(num_chapters_entry)

        ctk.CTkLabel(chapter_frame, text="Target Words/Chapter:").grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )
        self.words_chapter_var = StringVar()
        words_chapter_entry = ctk.CTkEntry(
            chapter_frame, textvariable=self.words_chapter_var, width=120
        )
        words_chapter_entry.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        self.input_widgets.append(words_chapter_entry)

        ctk.CTkLabel(
            chapter_frame, text="Chapter Details:\n(One line per chapter)"
        ).grid(row=2, column=0, sticky="nw", padx=10, pady=(10, 5))
        self.chapter_details_text = ctk.CTkTextbox(
            chapter_frame, wrap="word"
        ) # Removed fixed height
        self.chapter_details_text.grid(
            row=2, column=1, sticky="nsew", padx=10, pady=5
        ) # Use nsew
        self.input_widgets.append(self.chapter_details_text)

        # --- Optional Context ---
        ctk.CTkLabel(
            main_frame, text="Optional Context", font=ctk.CTkFont(weight="bold")
        ).grid(
            row=2, column=1, sticky="w", padx=10, pady=(15, 2)
        ) # Column 1
        context_frame = ctk.CTkFrame(main_frame)
        context_frame.grid(
            row=3, column=1, sticky="nsew", padx=10, pady=5
        ) # Column 1, nsew
        context_frame.grid_columnconfigure(1, weight=1)
        # Allow textbox rows to expand
        context_frame.grid_rowconfigure(0, weight=1)
        context_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(context_frame, text="Character Bios:").grid(
            row=0, column=0, sticky="nw", padx=10, pady=(10, 5)
        )
        self.char_bios_text = ctk.CTkTextbox(
            context_frame, wrap="word"
        ) # Removed fixed height
        self.char_bios_text.grid(
            row=0, column=1, sticky="nsew", padx=10, pady=5
        ) # Use nsew
        self.input_widgets.append(self.char_bios_text)

        ctk.CTkLabel(context_frame, text="World-Building:").grid(
            row=1, column=0, sticky="nw", padx=10, pady=(10, 5)
        )
        self.world_notes_text = ctk.CTkTextbox(
            context_frame, wrap="word"
        ) # Removed fixed height
        self.world_notes_text.grid(
            row=1, column=1, sticky="nsew", padx=10, pady=5
        ) # Use nsew
        self.input_widgets.append(self.world_notes_text)

        # --- Bottom Section (Spanning Both Columns) ---

        # --- Controls ---
        control_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        # Place in row 6, span 2 columns
        control_frame.grid(
            row=6, column=0, columnspan=2, sticky="ew", padx=5, pady=5
        )
        control_frame.grid_columnconfigure(0, weight=1) # Make generate button expand
        control_frame.grid_columnconfigure(1, weight=0) # Clear button fixed size

        self.generate_button = ctk.CTkButton(
            control_frame,
            text="Generate Book",
            command=self.start_generation_thread,
            height=35,
        )
        self.generate_button.grid(
            row=0, column=0, padx=(5, 2), pady=5, sticky="ew"
        )

        clear_log_button = ctk.CTkButton(
            control_frame, text="Clear Log", command=self.clear_log, width=100
        )
        clear_log_button.grid(row=0, column=1, padx=(2, 5), pady=5, sticky="e")

        # --- Output Log ---
        ctk.CTkLabel(
            main_frame, text="Output Log", font=ctk.CTkFont(weight="bold")
        ).grid(
            row=7, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 2)
        ) # Row 7, Span 2
        log_frame = ctk.CTkFrame(main_frame) # Frame to contain the textbox
        # Place in row 8, span 2 columns, stick nsew
        log_frame.grid(
            row=8, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10)
        )
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self.log_area = ctk.CTkTextbox(log_frame, wrap="word", state="disabled")
        self.log_area.grid(row=0, column=0, sticky="nsew")

        # Start polling the queue for updates
        self.root.after(100, self.process_queue)

    def clear_log(self):
        self.log_area.configure(state="normal")
        self.log_area.delete("1.0", "end")
        self.log_area.configure(state="disabled")

    def set_gui_state(self, enabled):
        """Enable or disable input widgets and generate button."""
        state = "normal" if enabled else "disabled"

        for widget in self.input_widgets:
            if widget and hasattr(widget, "configure"):
                try:
                    if isinstance(widget, ctk.CTkScrollableFrame):
                        # Disabling the frame itself might not prevent scrolling
                        # but disabling contained widgets is key.
                        # Let's try disabling the frame too.
                        widget.configure(state=state)
                        # Also disable internal widgets explicitly
                        for child in widget.winfo_children():
                            if hasattr(child, "configure"):
                                child.configure(state=state)
                    else:
                        widget.configure(state=state)
                except Exception as e:
                    print(
                        f"Warning: Could not set state for widget {widget}: {e}"
                    )
                    pass

        if self.generate_button and hasattr(self.generate_button, "configure"):
            self.generate_button.configure(state=state)

    def log_to_gui(self, message):
        """Appends a message to the log area."""
        # Ensure widget exists before configuring
        if self.log_area:
            self.log_area.configure(state="normal")
            self.log_area.insert("end", message + "\n")
            self.log_area.see("end") # Scroll to the end
            self.log_area.configure(state="disabled")

    def process_queue(self):
        """Process messages from the worker thread queue."""
        try:
            while True:
                message_type, data = gui_queue.get_nowait()

                if message_type == "log":
                    self.log_to_gui(data)
                elif message_type == "askyesno":
                    title, question, result_queue = data
                    result = messagebox.askyesno(
                        title, question, parent=self.root
                    )
                    result_queue.put(result)
                elif message_type == "askstring":
                    title, prompt, result_queue = data
                    dialog = ctk.CTkInputDialog(text=prompt, title=title)
                    # Make dialog modal (wait for it) relative to root
                    result = dialog.get_input()
                    result_queue.put(result)
                elif message_type == "showinfo":
                    title, message = data
                    messagebox.showinfo(title, message, parent=self.root)
                elif message_type == "showerror":
                    title, message = data
                    messagebox.showerror(title, message, parent=self.root)
                elif message_type == "showwarning":
                    title, message = data
                    messagebox.showwarning(title, message, parent=self.root)
                elif message_type == "generation_finished":
                    self.set_gui_state(enabled=True)
                    if not data:
                        self.log_to_gui("--- Generation Halted ---")

        except queue.Empty:
            pass
        finally:
            # Check again soon, only if root window still exists
            if self.root and self.root.winfo_exists():
                self.root.after(100, self.process_queue)

    def start_generation_thread(self):
        """Gathers inputs, validates, and starts the generation thread."""
        inputs = {}
        errors = []

        # Gather Inputs
        inputs["apiKey"] = self.api_key_var.get().strip()
        inputs["apiLevel"] = self.api_level_var.get()
        inputs["bookName"] = self.book_name_var.get().strip()
        inputs["bookBrief"] = self.brief_text.get("1.0", "end").strip()
        inputs["characterBios"] = self.char_bios_text.get("1.0", "end").strip()
        inputs["worldNotes"] = self.world_notes_text.get("1.0", "end").strip()
        inputs["regenOnLowWords"] = self.regen_low_words_var.get()
        inputs["bookGenre"] = [
            genre for genre, var in self.genre_vars.items() if var.get()
        ]

        # Output Format
        inputs["outputFormat"] = []
        if self.output_txt_var.get():
            inputs["outputFormat"].append("txt")
        if self.output_pdf_var.get():
            if not REPORTLAB_AVAILABLE:
                errors.append(
                    "PDF output selected, but 'reportlab' library is not installed. Please install it (pip install reportlab) or deselect PDF."
                )
            else:
                inputs["outputFormat"].append("pdf")

        num_chapters_str = self.num_chapters_var.get().strip()
        words_chapter_str = self.words_chapter_var.get().strip()
        try:
            inputs["numberOfChapters"] = int(num_chapters_str)
            if not (1 <= inputs["numberOfChapters"] <= 200):
                errors.append("Number of Chapters must be between 1 and 200.")
        except ValueError:
            if num_chapters_str:
                errors.append("Number of Chapters must be a valid integer.")
            else:
                errors.append("Number of Chapters is required.")
            inputs["numberOfChapters"] = 0

        try:
            inputs["wordsPerChapter"] = int(words_chapter_str)
            if not (100 <= inputs["wordsPerChapter"] <= 15000):
                errors.append(
                    "Words Per Chapter must be between 100 and 15000."
                )
        except ValueError:
            if words_chapter_str:
                errors.append("Words Per Chapter must be a valid integer.")
            else:
                errors.append("Words Per Chapter is required.")
            inputs["wordsPerChapter"] = 0

        raw_details = self.chapter_details_text.get("1.0", "end").strip()
        if raw_details:
            inputs["chapterDetails_list"] = [
                line.strip() for line in raw_details.split("\n") if line.strip()
            ]
            if (
                inputs["numberOfChapters"] > 0
                and len(inputs["chapterDetails_list"])
                != inputs["numberOfChapters"]
            ):
                errors.append(
                    f"Expected {inputs['numberOfChapters']} chapter detail lines, but found {len(inputs['chapterDetails_list'])}."
                )
        else:
            inputs["chapterDetails_list"] = []
            if inputs["numberOfChapters"] > 0:
                errors.append(
                    "Chapter Details cannot be empty (one line per chapter)."
                )

        if not inputs["apiKey"]:
            errors.append("API Key is required.")
        if not inputs["bookName"]:
            errors.append("Book Name is required.")
        if not inputs["bookGenre"]:
            errors.append("At least one Genre must be selected.")
        if not inputs["bookBrief"]:
            errors.append("Book Brief/Plot is required.")
        if not inputs["outputFormat"]:
            errors.append("At least one Output Format (TXT or PDF) must be selected.")


        if errors:
            messagebox.showerror(
                "Input Error",
                "Please fix the following errors:\n\n- " + "\n- ".join(errors),
                parent=self.root,
            )
            return

        # Calculate Filenames and Check Overwrite
        safe_book_name = "".join(
            c for c in inputs["bookName"] if c.isalnum() or c in (" ", "_")
        ).rstrip()
        base_filename = f"{safe_book_name.replace(' ', '_')}"
        txt_filename = f"{base_filename}.txt"
        pdf_filename = f"{base_filename}.pdf"
        inputs["txt_full_path"] = os.path.join(OUTPUT_DIR, txt_filename)
        inputs["pdf_full_path"] = os.path.join(OUTPUT_DIR, pdf_filename)

        files_to_check = []
        if "txt" in inputs["outputFormat"]:
            files_to_check.append(inputs["txt_full_path"])
        if "pdf" in inputs["outputFormat"]:
            files_to_check.append(inputs["pdf_full_path"])

        existing_files = [f for f in files_to_check if os.path.exists(f)]

        if existing_files:
            file_list_str = "\n - ".join(existing_files)
            if not messagebox.askyesno(
                "File Exists",
                f"The following output file(s) already exist:\n - {file_list_str}\n\nOverwrite?",
                parent=self.root,
            ):
                self.log_to_gui("Generation cancelled by user (file exists).")
                return
            else:
                try:
                    for f in existing_files:
                        os.remove(f)
                        self.log_to_gui(f"Existing file '{f}' will be overwritten.")
                except OSError as e:
                    messagebox.showerror(
                        "File Error",
                        f"Error removing existing file: {e}.\nPlease check permissions.\nCannot continue.",
                        parent=self.root,
                    )
                    return

        # --- Confirmation ---
        self.clear_log()
        self.log_to_gui("--- BOOK GENERATION SETTINGS ---")
        self.log_to_gui(f" - Book Name: {inputs['bookName']}")
        self.log_to_gui(f" - Book Genre: {', '.join(inputs['bookGenre'])}")
        self.log_to_gui(f" - Number of Chapters: {inputs['numberOfChapters']}")
        self.log_to_gui(
            f" - Target Words Per Chapter: {inputs['wordsPerChapter']}"
        )
        self.log_to_gui(f" - Output Formats: {', '.join(inputs['outputFormat']).upper()}")
        if "txt" in inputs["outputFormat"]:
             self.log_to_gui(f"   - TXT File: {inputs['txt_full_path']}")
        if "pdf" in inputs["outputFormat"]:
             self.log_to_gui(f"   - PDF File: {inputs['pdf_full_path']}")
        self.log_to_gui(
            f" - Regen on Low Word Count: {inputs['regenOnLowWords']}"
        )
        self.log_to_gui(
            f" - API Tier: {'Free' if inputs['apiLevel'] == 0 else 'Paid'}"
        )
        self.log_to_gui(
            f" - Character Notes Provided: {'Yes' if inputs['characterBios'] else 'No'}"
        )
        self.log_to_gui(
            f" - World Notes Provided: {'Yes' if inputs['worldNotes'] else 'No'}"
        )
        self.log_to_gui(
            f" - Chapter Details Provided: {len(inputs['chapterDetails_list'])} entries"
        )
        self.log_to_gui("---")

        if not messagebox.askyesno(
            "Confirm Generation",
            "Proceed with book generation using these settings?",
            parent=self.root,
        ):
            self.log_to_gui("Generation cancelled by user.")
            return

        # Disable GUI and Start Thread
        self.set_gui_state(enabled=False)
        self.log_to_gui("\n--- Starting Generation Thread ---")

        self.generation_thread = threading.Thread(
            target=run_generation_logic, args=(inputs,), daemon=True
        )
        self.generation_thread.start()


# ----- Main Execution ----- #

if __name__ == "__main__":
    # Optional: Improve DPI awareness on Windows
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except (ImportError, AttributeError):
        pass

    # Check for reportlab on startup and inform user if PDF is initially selected
    if not REPORTLAB_AVAILABLE:
        print(
            "WARNING: reportlab library not found. PDF output will be disabled in the GUI."
        )
        print("Install it using: pip install reportlab")
        # Consider showing a popup here too, but let's rely on the check during generation start for now.

    root = ctk.CTk()
    app = BookGenApp(root)
    root.mainloop()
