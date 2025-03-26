# INFO
# - MAX requests per minute = [FREE: 15], [TIER 1: 2000], [TIER 2: 10,000]

import requests as r
from time import sleep
import json
from math import ceil
import os
import sys
import traceback # For better error reporting

# -----FUNCTIONS & VARIABLES----- #

# Create a directory to store book files if it doesn't exist
OUTPUT_DIR = "books"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Constants ---
QUOTA_EXCEEDED_ERROR_STRING = "QUOTA_EXCEEDED"
MAX_GENERATION_ATTEMPTS = 4 # Max attempts for generating a single piece (chapter/sub/outline chunk)
OUTLINE_CHUNK_THRESHOLD = 15 # Generate outline in chunks if total items > this
CHAPTERS_PER_OUTLINE_CHUNK = 3 # How many chapters to outline per API call in chunked mode

def split_string_into_chunks(input_string, chunk_length):
    """
    Split a long string into chunks of specified length,
    ensuring chunks break at word boundaries.

    Args:
        input_string (str): The string to be chunked
        chunk_length (int): Maximum length of each chunk

    Returns:
        str: A string with chunks separated by newline characters
    """
    if not input_string:
        return ''
    words = input_string.split()
    chunks = []
    current_chunk = []
    current_length = 0
    for word in words:
        word_len = len(word)
        potential_len = current_length + word_len + (1 if current_length > 0 else 0)
        if potential_len > chunk_length:
            if current_chunk: # Don't add empty chunks
                chunks.append(' '.join(current_chunk))
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
        chunks.append(' '.join(current_chunk))
    return '\n'.join(chunks)

def writeToFile(filename, content):
    """Appends content to a file."""
    try:
        # Use 'a' mode for appending
        with open(filename, "a", encoding="utf-8") as f:
            f.write(content)
    except IOError as e:
        print(f"Error writing to file {filename}: {e}")
        # Consider if you want to exit or handle this differently
        # For critical writes, exiting might be appropriate
        print("Exiting due to file write error.")
        sys.exit(1)

def removeBrackets(text=""):
    """Removes '<' and '>' characters from a string."""
    if not isinstance(text, str):
        print(f"Warning: removeBrackets received non-string input: {type(text)}")
        return text # Return input as-is if not a string
    text = text.replace(">", "")
    text = text.replace("<", "")
    return text

# to generate a prompt
def generatePrompt(option, bookName, bookGenre, numberOfChapters, bookBrief, combinedChapterDetails,
                   wordsPerChapter, wordsPerSubchapter, bookOutline, numberOfSubchapters,
                   lastGeneratedSubchapter_Full, # Pass more context
                   lastGeneratedChapter_Full,   # Pass more context
                   currentChapter, currentSubchapter,
                   character_bios="", world_notes="", # NEW Optional context
                   start_chapter_chunk=None, end_chapter_chunk=None, previous_outline_context=""):
    """Generates prompts for the AI.
    1 = outline (full or chunk), 2 = chapter gen, 3 = sub-chapter gen.
    """
    wordsPerChapter_int = int(wordsPerChapter)
    wordsPerSubchapter_int = int(wordsPerSubchapter) if wordsPerSubchapter else 0

    bookGenre_str = ", ".join(bookGenre) if isinstance(bookGenre, list) else bookGenre

    # --- Context Snippets (Use more context) ---
    # Limit context to avoid excessive token usage, prioritize end
    MAX_CONTEXT_CHARS = 2000 # Increased context length
    prev_chap_context = f"... {lastGeneratedChapter_Full[-MAX_CONTEXT_CHARS:]}" if lastGeneratedChapter_Full else "N/A - This is the first chapter."
    prev_sub_context = f"... {lastGeneratedSubchapter_Full[-MAX_CONTEXT_CHARS:]}" if lastGeneratedSubchapter_Full else "N/A - This is the first sub-chapter of the chapter or book."
    # ---

    # --- Optional Context Inclusion ---
    character_context = f"\n- Character Notes: {character_bios}" if character_bios else ""
    world_context = f"\n- World/Setting Notes: {world_notes}" if world_notes else ""
    # ---

    if option == 1: # outline
        # --- Outline Prompt Refinements ---
        sub_needed_text = "Yes" if numberOfSubchapters > 0 else "No"
        sub_instruction = f"Generate EXACTLY {numberOfSubchapters} sub-chapters per chapter." if numberOfSubchapters > 0 else "DO NOT generate sub-chapters."

        is_chunked_request = start_chapter_chunk is not None and end_chapter_chunk is not None
        if is_chunked_request:
            task_description = f"You are generating PART of a 'Book Outline' for chapters {start_chapter_chunk} through {end_chapter_chunk}."
            chapter_range_instruction = f"ONLY generate the outline details for chapters {start_chapter_chunk} to {end_chapter_chunk} inclusive."
            context_instruction = f"Ensure the summaries for these chapters flow logically from the previous part of the outline and contribute to the overall plot arc. The end of the previous section is:\n\"... {previous_outline_context[-1000:]}\"" if previous_outline_context else "This is the first chunk of the outline." # Keep context reasonable
        else:
            task_description = "You are an AI that is made for generating a complete 'Book Outline' based on simple information given about a book."
            chapter_range_instruction = f"Generate the outline for ALL {numberOfChapters} chapters."
            context_instruction = "The whole book outline should form a coherent narrative structure. Each chapter summary must advance the plot, develop characters, or build the world, contributing logically to the overall story arc."

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
    # STORYTELLING FOCUS FOR CHAPTERS/SUB-CHAPTERS
    elif option == 2 or option == 3:
        unit_type = "chapter" if option == 2 else "sub-chapter"
        current_unit_num = currentChapter if option == 2 else f"{currentChapter}-{currentSubchapter}"
        target_words = wordsPerChapter_int if option == 2 else wordsPerSubchapter_int
        min_target_words = int(target_words * 0.85)
        last_content_context = prev_chap_context if option == 2 else prev_sub_context # Use the larger context

        # Extract relevant outline section (This requires parsing G_bookOutline effectively)
        # Placeholder for finding the specific outline - you'll need robust parsing here
        relevant_outline = f"[ERROR: Could not extract outline for {unit_type} {current_unit_num}]"
        try:
             # Basic parsing attempt - needs refinement based on your exact outline format
             outline_lines = bookOutline.splitlines()
             search_str_chap = f"Chapter: {currentChapter}:"
             search_str_sub = f"- Sub-Chapter: {currentSubchapter}:" if option == 3 else None
             in_correct_section = False
             section_lines = []
             for line in outline_lines:
                  stripped_line = line.strip()
                  if option == 2: # Chapter
                       if stripped_line.startswith(search_str_chap):
                            in_correct_section = True
                            section_lines.append(line) # Include header
                            continue
                       elif in_correct_section and (stripped_line.startswith("Chapter:") or not stripped_line):
                            # Reached next chapter or empty line after chapter content
                            break
                  elif option == 3: # Sub-chapter
                       if stripped_line.startswith(search_str_sub):
                            in_correct_section = True
                            section_lines.append(line) # Include header
                            continue
                       elif in_correct_section and (stripped_line.startswith("- Sub-Chapter:") or stripped_line.startswith("Chapter:") or not stripped_line):
                             # Reached next sub-chapter, next chapter, or empty line
                            break

                  if in_correct_section and stripped_line:
                       # Add summary lines for the correct section
                       section_lines.append(line)

             if section_lines:
                  relevant_outline = "\n".join(section_lines)
             else:
                 print(f"Warning: Could not parse specific outline for {unit_type} {current_unit_num} from G_bookOutline.")
                 # Fallback: Provide broader context if specific part not found?
                 # relevant_outline = bookOutline # Or maybe just the chapter part? Risky.

        except Exception as e:
             print(f"Error parsing outline for prompt: {e}")


        # --- STORYTELLING INSTRUCTIONS ---
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
        # --- END STORYTELLING INSTRUCTIONS ---

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
        print(f"Error: Incorrect option number '{option}' passed to generatePrompt.")
        return "Error: Incorrect option number"

def getResponse(apiKey, prompt, max_tokens=8192):
    """Make API call to Gemini with error handling, quota detection, and token management."""
    # Use 2.0 flash latest stable
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent?key={apiKey}" # Using 2.0 Flash for potentially better context handling

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
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
    }

    try:
        # Increased timeout for potentially longer generations
        response = r.post(url, headers=headers, json=payload, timeout=300) # Increased timeout slightly

        # Attempt to parse JSON regardless of status code for more detailed error info
        try:
            data = response.json()
        except json.JSONDecodeError:
            # If JSON decoding fails, use the raw text
            print(f"API Error: Status Code {response.status_code}, Non-JSON Response:")
            print(response.text[:500]) # Print first 500 chars of response
             # Check specifically for Quota Exceeded (429) even with non-JSON response
            if response.status_code == 429:
                print("Quota limit likely reached (Status 429).")
                return QUOTA_EXCEEDED_ERROR_STRING # Return special string for quota error
            return f"API Error: {response.status_code} - Non-JSON Response"

        # Check for explicit errors in the JSON response first
        if 'error' in data:
            error_info = data['error']
            status_code = error_info.get('code', response.status_code) # Get code from error payload if available
            error_message = error_info.get('message', 'Unknown error structure')
            print(f"API Error: {status_code} - {error_message}")

            # --- QUOTA CHECK ---
            # Check status code 429 or common quota messages
            if status_code == 429 or "quota" in error_message.lower() or "rate limit" in error_message.lower():
                 print("Quota limit likely reached.")
                 return QUOTA_EXCEEDED_ERROR_STRING # Return special string for quota error
            # --- END QUOTA CHECK ---

            return f"API Error: {status_code} - {error_message}"

        # Check status code *after* checking for JSON error field
        if response.status_code == 200:
            # Navigate through the JSON structure to extract the message text
            try:
                candidate = data.get("candidates", [{}])[0] # Use .get for safety
                finish_reason = candidate.get("finishReason", "UNKNOWN")

                # Check for problematic finish reasons
                if finish_reason not in ["STOP", "MAX_TOKENS"]:
                    safety_ratings = candidate.get("safetyRatings", [])
                    print(f"Warning: Generation finished with reason: {finish_reason}")
                    # Check if content exists despite the finish reason
                    content = candidate.get("content", {})
                    parts = content.get("parts", [{}])
                    if parts and "text" in parts[0]:
                        message = parts[0]["text"]
                        print("  (Content might be partial or incomplete)")
                        # Decide whether to return partial content or error
                        # For now, let's return it but the calling code should be aware
                        # return message # Option 1: Return potentially partial content
                        return f"API Warning: Generation finished unexpectedly ({finish_reason}), content may be incomplete." # Option 2: Return warning string
                    else:
                        # If no content AND bad finish reason (e.g., SAFETY)
                        if safety_ratings:
                            print("Safety Ratings:")
                            for rating in safety_ratings:
                                print(f"  - {rating['category']}: {rating['probability']}")
                        return f"API Error: Generation stopped ({finish_reason}) with no content."


                # Check if content parts exist (even if finishReason is STOP/MAX_TOKENS)
                content = candidate.get("content", {})
                parts = content.get("parts", [{}])
                if parts and "text" in parts[0]:
                    message = parts[0]["text"]
                    if finish_reason == "MAX_TOKENS":
                        print("Warning: Max output tokens reached. Content might be truncated.")
                    return message
                else:
                    # Handle cases where response is successful but no text part is found
                    print("API Error: Response successful, but no text content found.")
                    print("Response data:", json.dumps(data, indent=2)) # Pretty print data
                    safety_ratings = candidate.get("safetyRatings", [])
                    if safety_ratings:
                         print("Safety Ratings:")
                         for rating in safety_ratings:
                              print(f"  - {rating['category']}: {rating['probability']}")
                    # This often happens due to safety filters even if finishReason isn't SAFETY
                    return "API Error: No text content found in response (possibly blocked by safety filter)"

            except (KeyError, IndexError, TypeError) as e:
                print(f"Error parsing successful response: {e}")
                print("Response data:", json.dumps(data, indent=2))
                return f"Error parsing response: {e}"
        else:
             # --- QUOTA CHECK (for non-200 status not caught earlier) ---
            if response.status_code == 429:
                print("Quota limit likely reached (Status 429).")
                return QUOTA_EXCEEDED_ERROR_STRING
            # --- END QUOTA CHECK ---
            # Use the error message from JSON if available, otherwise status code
            error_detail = data.get('error', {}).get('message', f'Status Code {response.status_code}')
            print(f"API Error: {error_detail}")
            print("Response data:", json.dumps(data, indent=2))
            return f"API Error: {error_detail}"

    except r.exceptions.Timeout:
        print(f"Request timed out after {300} seconds.")
        return "API Error: Request Timeout"
    except r.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return f"Request failed: {e}"
    except Exception as e:
        # Catch any other unexpected errors during the request/processing
        print(f"An unexpected error occurred in getResponse: {e}")
        traceback.print_exc()
        return f"Unexpected Error: {e}"

# --- Global Variables (User Input - Initialized Empty/Default) ---
I_bookName = ""
I_bookGenre = [] # Store as list now
I_wordsPerChapter = 0
I_numberOfChapters = 0
I_chapterDetails = []
I_bookBrief = ""
I_apiKey = ""
I_apiLevel = 0 # 0 for free, 1 for tier 1+
I_characterBios = "" # NEW
I_worldNotes = ""    # NEW

# --- Global Variables (Derived/Runtime) ---
G_bookOutline = ""
numberOfSubchapters = 0
wordsPerSubchapter = 0.0
combinedChapterDetails = ""
totalWords = 0
currentChapter = 0
currentSubChapter = 0
lastGeneratedChapter = ""
lastGeneratedSubchapter = ""
totalGeneratedWords = 0
waitTime = 5
regenOnLowWords = False
regenOnOffTopic = False # Flag exists, but automatic check not implemented. Relies on prompt.
full_path = ""
total_outline_items = 0 # NEW: To store total chapters/sub-chapters for outline
lastGeneratedChapter_Full = "" # Store full text
lastGeneratedSubchapter_Full = "" # Store full text

# --- Helper for Quota Handling ---
def handle_quota_error():
    """Prompts user for a new API key and updates the global variable."""
    global I_apiKey
    print("\n--- API Quota Limit Reached ---")
    print("The current API key has likely reached its usage limit.")
    while True:
        new_key = input("Please enter a new Google AI API key (or press Enter to cancel): ").strip()
        if not new_key:
            print("No new key provided. Aborting generation.")
            return False # Indicate cancellation
        # Basic validation
        if len(new_key) > 30 and "AI" in new_key:
            I_apiKey = new_key
            print("API Key updated. Retrying the last request...")
            sleep(1) # Small delay before retry
            return True # Indicate success
        else:
            print("Invalid API key format. Please try again.")

def main():
    # Make global variables explicitly writable where necessary
    global I_bookName, I_bookGenre, I_wordsPerChapter, I_numberOfChapters
    global I_chapterDetails, I_bookBrief, I_apiKey, I_apiLevel
    global G_bookOutline, numberOfSubchapters, wordsPerSubchapter, combinedChapterDetails
    global totalWords, currentChapter, currentSubChapter
    # Use _Full for context storage
    global lastGeneratedChapter_Full, lastGeneratedSubchapter_Full
    global totalGeneratedWords, waitTime
    global regenOnLowWords, regenOnOffTopic, full_path, total_outline_items
    # Add new optional context globals
    global I_characterBios, I_worldNotes

    # ----- Step 0 ----- #
    print("-----Step 0. API key/s-----")
    # ... (Keep existing API key input and tier selection logic) ...
    while not I_apiKey:
        I_apiKey = input("Enter your Google AI API key: ").strip()
        if not (isinstance(I_apiKey, str) and len(I_apiKey) > 30 and "AI" in I_apiKey):
            print("\nWarning: API key format looks potentially incorrect. Ensure it's a valid Google AI key.")
            if input("Continue anyway? (y/n): ").lower() != 'y':
                I_apiKey = ""
            elif not I_apiKey:
                print("API Key cannot be empty.")

    print("\nPaying for the API can increase rate limits (requests/minute).")
    api_level_input = input("Are you using the free tier API key (limited requests/minute)? (y/n): ").lower()
    if api_level_input == 'y':
        I_apiLevel = 0
        waitTime = 5
        print("Using free tier settings (slower generation).")
    elif api_level_input == 'n':
        I_apiLevel = 1
        waitTime = 0.5
        print("Using paid tier settings (faster generation).")
    else:
        print("Invalid input for API level. Assuming free tier.")
        I_apiLevel = 0
        waitTime = 5
    print("-----Step 0. Done!-----\n")

    # ----- Step 1 -----
    print("-----Step 1. Book info-----")
    # ... (Keep existing Book Name input and file path setup) ...
    while not I_bookName:
        I_bookName = input("Enter book name: ").strip()
        if not I_bookName:
            print("Book name can't be empty!")

    safe_book_name = "".join(c for c in I_bookName if c.isalnum() or c in (' ', '_')).rstrip()
    I_fileName = f"{safe_book_name.replace(' ', '_')}.txt"
    full_path = os.path.join(OUTPUT_DIR, I_fileName)
    print(f"\nBook content will potentially be saved to: {full_path}")

    # ... (Keep existing file overwrite check logic) ...
    if os.path.exists(full_path):
        print(f"\nWARNING: Output file '{full_path}' already exists.")
        while True:
            choice = input("Choose an action: (O)verwrite, (C)ancel generation: ").lower().strip()
            if choice == 'o':
                try:
                    os.remove(full_path)
                    print(f"Existing file '{full_path}' will be overwritten.")
                except OSError as e:
                    print(f"Error removing existing file: {e}. Please check permissions.")
                    print("Cannot continue without ability to overwrite.")
                    sys.exit(1)
                break
            elif choice == 'c':
                print("Generation cancelled by user.")
                sys.exit(0)
            else:
                print("Invalid choice. Please enter 'O' or 'C'.")


    # ... (Keep existing Genre selection logic) ...
    book_generes = ["Fantasy", "Action/Adventure", "Literary Fiction", "Non-Fiction", "Dystopian", "Mystery", "Horror", "Thriller/Suspense", "Romance", "Childrens", "Memoir", "Sci-Fi", "Historical Fiction"]
    print("\nAvailable Book Genres:")
    for i, genre in enumerate(book_generes): print(f" - {i}: {genre}")
    selected_genre_indices = []
    while not selected_genre_indices:
        # ... (genre input validation logic remains the same) ...
         raw_input_genres = input(f"Enter book genre number(s) (0-{len(book_generes)-1}), comma separated (e.g., 1, 3): ")
         input_parts = raw_input_genres.split(',')
         valid_indices_found = []
         error_messages = []
         for part in input_parts:
             stripped_part = part.strip()
             if not stripped_part: continue
             try:
                 genre_choice = int(stripped_part)
                 if 0 <= genre_choice < len(book_generes):
                     if genre_choice not in valid_indices_found: valid_indices_found.append(genre_choice)
                     else: print(f"Note: Genre index {genre_choice} entered more than once.")
                 else: error_messages.append(f"Index '{genre_choice}' is out of range (0-{len(book_generes)-1}).")
             except ValueError: error_messages.append(f"Invalid input '{stripped_part}'. Please enter numbers only.")
         if error_messages:
             print("\nError(s) in genre selection:"); [print(f" - {msg}") for msg in error_messages]; print("Please try again.")
         elif not valid_indices_found: print("No valid genre numbers were entered. Please try again.")
         else:
             selected_genre_indices = sorted(valid_indices_found); I_bookGenre = [book_generes[i] for i in selected_genre_indices]; print(f"Selected Genres: {', '.join(I_bookGenre)}"); break

    # ... (Keep existing Book Brief input logic) ...
    print("\nBook Brief:")
    print(" - Explain the overall plot, main characters, setting, desired tone.")
    while not I_bookBrief:
        print("Enter a brief description of the book and its plot (end with EOF or empty line):")
        lines = []
        try:
            while True:
                line = input("> ") # Added prompt back for clarity
                if not line:
                    break
                lines.append(line)
        except EOFError:
            pass
        I_bookBrief = "\n".join(lines).strip()
        if not I_bookBrief:
            print("Book brief can't be empty!")

    # --- NEW: Optional Character/World Input ---
    print("\nOptional Context (Highly Recommended for Consistency):")
    if input("Add Character Bios/Notes? (y/n): ").lower() == 'y':
        print("Enter character notes (name, role, personality, goals, appearance, etc.). End with EOF or empty line:")
        lines = []
        try:
            while True:
                line = input("> ") # Added prompt back
                if not line:
                    break
                lines.append(line)
        except EOFError:
            pass
        I_characterBios = "\n".join(lines).strip()

    if input("Add World-Building/Setting Notes? (y/n): ").lower() == 'y':
        print("Enter world notes (locations, rules, history, tech, magic system, etc.). End with EOF or empty line:")
        lines = []
        try:
            while True:
                line = input("> ") # Added prompt back
                if not line:
                    break
                lines.append(line)
        except EOFError:
            pass
        I_worldNotes = "\n".join(lines).strip()
    # --- End Optional Input ---

    # ... (Keep existing Number of Chapters input logic) ...
    while True:
        try:
            I_numberOfChapters = int(input(f"\nHow many chapters should the book have? (1-100 recommended): "))
            if 1 <= I_numberOfChapters <= 200:
                if I_numberOfChapters > 100: print("Warning: Generating more than 100 chapters will take a very long time and many API calls.")
                break
            else: print("Please enter a number of chapters between 1 and 200.")
        except ValueError: print("Invalid input. Please enter a number.")

    # ... (Keep existing Chapter Details input logic) ...
    print("\nChapter Details:")
    print(" - Briefly outline what should happen in each chapter.")
    I_chapterDetails = []
    for i in range(1, I_numberOfChapters + 1):
        chapterDetail = "";
        while not chapterDetail: chapterDetail = input(f"Outline for Chapter {i}: ").strip();
        if not chapterDetail: print("Chapter outline cannot be empty.")
        I_chapterDetails.append(chapterDetail)
    combinedChapterDetails = " | ".join([f"Chapter {i+1} Outline: \"{detail}\"" for i, detail in enumerate(I_chapterDetails)])

    # ... (Keep existing Words Per Chapter input logic) ...
    print("\nFair warning, high word counts per chapter with many chapters will take significant time and API calls.")
    while True:
        try:
            I_wordsPerChapter = int(input("Enter target words per chapter (e.g., 500-5000 recommended): "))
            if 100 <= I_wordsPerChapter <= 15000:
                if I_wordsPerChapter > 7000: print("Warning: Target words per chapter is very high, generation may be slow or hit token limits.")
                break
            else: print("Please enter a target word count between 100 and 15000.")
        except ValueError: print("Invalid input. Please enter a number.")

    # --- Calculate dependent variables ---
    totalWords = I_wordsPerChapter * I_numberOfChapters
    SUBCHAPTER_THRESHOLD = 1500
    TARGET_SUBCHAPTER_WORDS = 500
    if I_wordsPerChapter > SUBCHAPTER_THRESHOLD:
        numberOfSubchapters = ceil(I_wordsPerChapter / TARGET_SUBCHAPTER_WORDS)
        numberOfSubchapters = max(3, numberOfSubchapters)
        wordsPerSubchapter = ceil(I_wordsPerChapter / numberOfSubchapters)
        print(f"\nChapters exceed {SUBCHAPTER_THRESHOLD} words, will be split into {numberOfSubchapters} sub-chapters of ~{int(wordsPerSubchapter)} words each.")
    else:
        numberOfSubchapters = 0; wordsPerSubchapter = 0

    if numberOfSubchapters > 0: total_outline_items = I_numberOfChapters * numberOfSubchapters
    else: total_outline_items = I_numberOfChapters
    print(f"Total outline items to generate: {total_outline_items}")

    # --- Adjust Word Count Multiplier ---
    # Reduce exaggeration, rely more on prompt quality
    word_multiplier = 1.8 # Start with 1.8x or 2.0x instead of 4x
    wordsPerSubchapter_gen = wordsPerSubchapter * word_multiplier if wordsPerSubchapter > 0 else 0
    wordsPerChapter_gen = I_wordsPerChapter * word_multiplier
    print(f"Adjusted Prompt Target Words/Chapter: ~{int(wordsPerChapter_gen)}")
    if numberOfSubchapters > 0:
       print(f"Adjusted Prompt Target Words/Sub-Chapter: ~{int(wordsPerSubchapter_gen)}")
    # ---

    # ... (Keep existing Regen on Low Words option) ...
    if input("\nRegenerate chapter/sub-chapter if word count is too low? (y/n): ").lower() == 'y': regenOnLowWords = True
    else: regenOnLowWords = False
    regenOnOffTopic = False # Keep as false

    # --- Confirmation ---
    print("\n-----Step 1. Done!-----")
    print("\n--- BOOK GENERATION SETTINGS ---")
    # ... (Keep existing confirmation print statements) ...
    print(f" - Book Name: {I_bookName}")
    print(f" - Book Genre: {', '.join(I_bookGenre)}")
    print(f" - Number of Chapters: {I_numberOfChapters}")
    print(f" - Sub-Chapters per Chapter: {numberOfSubchapters}" + (f" (~{int(wordsPerSubchapter)} words each)" if numberOfSubchapters > 0 else " (Not Needed)"))
    print(f" - Target Words Per Chapter (User Input): {I_wordsPerChapter}")
    print(f" - Prompt Target Words/Chapter (Adjusted): ~{int(wordsPerChapter_gen)}")
    print(f" - Est. Total Target Words: {totalWords}")
    print(f" - Total Outline Items: {total_outline_items}")
    print(f" - Output File: {full_path}")
    print(f" - Regen on Low Word Count: {regenOnLowWords}")
    print(f" - API Wait Time: {waitTime} seconds between requests")
    print(f" - Character Notes Provided: {'Yes' if I_characterBios else 'No'}")
    print(f" - World Notes Provided: {'Yes' if I_worldNotes else 'No'}")
    print("---")

    if input("\nProceed with book generation using these settings? (y/n): ").lower() != 'y':
        print("Generation cancelled.")
        sys.exit(0)

    # ----- Step 2. Generation -----
    print("\n-----Step 2. Generation-----")
    print(" - Generating book outline and content...")
    print(" - This may take a significant amount of time.")
    print(" - Press Ctrl+C to interrupt (progress up to interruption will be saved).")

    # --- Generate Book Outline ---
    print("\nGenerating Book Outline...")
    G_bookOutline = ""
    outline_generated_successfully = False
    outline_regeneration_requested = False

    while not outline_generated_successfully or outline_regeneration_requested:
        outline_regeneration_requested = False
        G_bookOutline = ""
        full_outline_parts = []
        previous_outline_context = ""
        outline_generation_failed = False

        if total_outline_items > OUTLINE_CHUNK_THRESHOLD:
            print(f"Outline has {total_outline_items} items, exceeding threshold {OUTLINE_CHUNK_THRESHOLD}. Generating in chunks...")
            num_chunks = ceil(I_numberOfChapters / CHAPTERS_PER_OUTLINE_CHUNK)
            print(f"Total Chunks: {num_chunks}")

            for chunk_index in range(num_chunks):
                start_chap = chunk_index * CHAPTERS_PER_OUTLINE_CHUNK + 1
                end_chap = min((chunk_index + 1) * CHAPTERS_PER_OUTLINE_CHUNK, I_numberOfChapters)
                print(f"\nGenerating Outline Chunk {chunk_index + 1}/{num_chunks} (Chapters {start_chap}-{end_chap})...")

                chunk_generated_successfully = False
                attempt = 1
                while attempt <= MAX_GENERATION_ATTEMPTS and not chunk_generated_successfully:
                    print(f"  Attempt {attempt}/{MAX_GENERATION_ATTEMPTS}...")
                    # *** MODIFIED CALL ***
                    outline_prompt = generatePrompt(1, I_bookName, I_bookGenre, I_numberOfChapters,
                                                    I_bookBrief, combinedChapterDetails,
                                                    wordsPerChapter_gen, wordsPerSubchapter_gen,
                                                    "", numberOfSubchapters, "", "", 0, 0,
                                                    character_bios=I_characterBios, # ADDED
                                                    world_notes=I_worldNotes,       # ADDED
                                                    start_chapter_chunk=start_chap,
                                                    end_chapter_chunk=end_chap,
                                                    previous_outline_context=previous_outline_context)

                    response = getResponse(I_apiKey, outline_prompt, max_tokens=6144)
                    # ... (Keep existing error handling, quota check, retry logic for chunks) ...
                    if response == QUOTA_EXCEEDED_ERROR_STRING:
                        if not handle_quota_error(): outline_generation_failed = True; break
                        continue
                    elif response.startswith("API Error:") or response.startswith("Error parsing") or response.startswith("Request failed:") or response.startswith("Unexpected Error:") or response.startswith("API Warning:"):
                        print(f"  Error/Warning generating outline chunk {chunk_index + 1} (Attempt {attempt}): {response}")
                        if attempt == MAX_GENERATION_ATTEMPTS: print(f"  Max attempts reached for chunk {chunk_index + 1}."); outline_generation_failed = True; break
                        else: print(f"  Waiting {waitTime*2}s before retry..."); sleep(waitTime * 2)
                        attempt += 1; continue
                    chunk_text = removeBrackets(response)
                    full_outline_parts.append(chunk_text)
                    previous_outline_context = chunk_text
                    print(f"  Outline Chunk {chunk_index + 1} generated successfully.")
                    chunk_generated_successfully = True
                    sleep(waitTime)
                if outline_generation_failed or not chunk_generated_successfully: break # Break outer chunk loop
            if not outline_generation_failed: G_bookOutline = "\n\n".join(full_outline_parts); outline_generated_successfully = True; print("Full Outline Assembled!")
        else:
            # --- Single Call Outline Generation ---
            print("Generating outline in a single call...")
            attempt = 1
            single_call_success = False
            while attempt <= MAX_GENERATION_ATTEMPTS and not single_call_success:
                 print(f"  Attempt {attempt}/{MAX_GENERATION_ATTEMPTS}...")
                 # *** MODIFIED CALL ***
                 outline_prompt = generatePrompt(1, I_bookName, I_bookGenre, I_numberOfChapters,
                                                I_bookBrief, combinedChapterDetails,
                                                wordsPerChapter_gen, wordsPerSubchapter_gen,
                                                "", numberOfSubchapters, "", "", 0, 0,
                                                character_bios=I_characterBios, # ADDED
                                                world_notes=I_worldNotes)      # ADDED

                 response = getResponse(I_apiKey, outline_prompt, max_tokens=8192)
                 # ... (Keep existing error handling, quota check, retry logic for single call) ...
                 if response == QUOTA_EXCEEDED_ERROR_STRING:
                     if not handle_quota_error(): outline_generation_failed = True; break
                     continue
                 elif response.startswith("API Error:") or response.startswith("Error parsing") or response.startswith("Request failed:") or response.startswith("Unexpected Error:") or response.startswith("API Warning:"):
                     print(f"  Error/Warning during single outline generation (Attempt {attempt}): {response}")
                     if attempt == MAX_GENERATION_ATTEMPTS: print(f"  Max attempts reached for single outline generation."); outline_generation_failed = True; break
                     else: print(f"  Waiting {waitTime*2}s before retry..."); sleep(waitTime * 2)
                     attempt += 1; continue
                 G_bookOutline = removeBrackets(response)
                 single_call_success = True
                 outline_generated_successfully = True
                 print("Book Outline Generation Complete!")
                 sleep(waitTime)
            if outline_generation_failed:
                 if input("Retry outline generation? (y/n): ").lower() != 'y': sys.exit(1)
                 else: outline_generated_successfully = False; continue # Restart while loop

        # --- Post-Generation Handling ---
        if outline_generated_successfully:
            print("\n--- Generated Outline (Preview) ---")
            print(f"\033[38;2;100;100;255m{G_bookOutline[:1000]}...\033[0m")
            print("--- End Outline Preview ---\n")
            if input("Regenerate outline if not satisfactory? (y/n): ").lower() == 'y':
                print("Regenerating Book Outline..."); outline_regeneration_requested = True; outline_generated_successfully = False;
            else: print("Keeping the generated outline.")
        elif not outline_regeneration_requested: print("Fatal Error: Could not generate book outline."); sys.exit(1)

    # --- Write Header Info and Outline to File ---
    print(f"Writing header and final outline to {full_path}...")
    initial_content = f"Book Title: {I_bookName}\n"
    initial_content += f"Genre: {', '.join(I_bookGenre)}\n"
    initial_content += f"Target Chapters: {I_numberOfChapters}\n"
    initial_content += f"Target Words/Chapter (Prompt): ~{int(wordsPerChapter_gen)}\n" # Use adjusted
    initial_content += f"Sub-Chapters/Chapter: {numberOfSubchapters}\n"
    if numberOfSubchapters > 0:
        initial_content += f"Target Words/Sub-Chapter (Prompt): ~{int(wordsPerSubchapter_gen)}\n" # Use adjusted
    # Add optional context to header
    if I_characterBios:
        initial_content += "\n----- CHARACTER NOTES -----\n"
        initial_content += I_characterBios + "\n"
    if I_worldNotes:
        initial_content += "\n----- WORLD NOTES -----\n"
        initial_content += I_worldNotes + "\n"
    initial_content += "\n----- BOOK OUTLINE -----\n"
    initial_content += G_bookOutline
    initial_content += "\n\n----- BOOK CONTENT -----\n"

    try:
        with open(full_path, "w", encoding="utf-8") as f: f.write(initial_content)
    except IOError as e: print(f"FATAL ERROR: Could not write initial header to file {full_path}: {e}"); sys.exit(1)

    # --- Generate Book Contents ---
    print("\nStarting Chapter/Sub-Chapter Generation...")
    totalGeneratedWords = 0
    lastGeneratedChapter_Full = "" # Reset before loop, use _Full

    for chap_num in range(1, I_numberOfChapters + 1):
        currentChapter = chap_num
        chapter_header = f"\n\n---------- Chapter: {currentChapter} ----------\n\n"
        print(f"\n----- Generating Chapter: {currentChapter}/{I_numberOfChapters} -----")
        writeToFile(full_path, chapter_header)
        lastGeneratedSubchapter_Full = "" # Reset for each new chapter, use _Full
        current_chapter_content_parts = []
        target_word_count_tolerance = 0.20

        if numberOfSubchapters > 0:
            # --- Sub-Chapter Generation ---
            target_words_sub = int(wordsPerSubchapter_gen) # Use adjusted
            min_words_sub = int(target_words_sub * (1 - target_word_count_tolerance))

            for sub_chap_num in range(1, numberOfSubchapters + 1):
                currentSubChapter = sub_chap_num
                print(f"  Generating Sub-Chapter: {currentSubChapter}/{numberOfSubchapters}...")
                sub_chapter_generated_successfully = False
                attempt = 1
                while attempt <= MAX_GENERATION_ATTEMPTS and not sub_chapter_generated_successfully:
                    print(f"    Attempt {attempt}/{MAX_GENERATION_ATTEMPTS}...")
                    # *** MODIFIED CALL ***
                    prompt = generatePrompt(3, I_bookName, I_bookGenre, I_numberOfChapters,
                                            I_bookBrief, combinedChapterDetails,
                                            wordsPerChapter_gen, wordsPerSubchapter_gen, # Adjusted words
                                            G_bookOutline, numberOfSubchapters,
                                            lastGeneratedSubchapter_Full, # Full context
                                            lastGeneratedChapter_Full,    # Full context
                                            currentChapter, currentSubChapter,
                                            character_bios=I_characterBios, # Added
                                            world_notes=I_worldNotes)      # Added

                    response = getResponse(I_apiKey, prompt)
                    # ... (Keep existing error handling, quota check, retry logic for sub-chapters) ...
                    if response == QUOTA_EXCEEDED_ERROR_STRING:
                        if not handle_quota_error(): sys.exit(1)
                        continue
                    elif response.startswith("API Error:") or response.startswith("Error parsing") or response.startswith("Request failed:") or response.startswith("Unexpected Error:") or response.startswith("API Warning:"):
                        print(f"    Error/Warning generating sub-chapter {currentChapter}-{currentSubChapter} (Attempt {attempt}): {response}")
                        if attempt == MAX_GENERATION_ATTEMPTS: print(f"    Max attempts reached. Skipping sub-chapter {currentChapter}-{currentSubChapter}."); writeToFile(full_path, f"\n\n!! ERROR: SUB-CHAPTER {currentChapter}-{currentSubChapter} !!\n{response}\n")
                        else: print(f"    Waiting {waitTime*2}s before retry..."); sleep(waitTime * 2)
                        attempt += 1; continue

                    generated_text = response
                    word_count = len(generated_text.split())
                    print(f"    Sub-Chapter {currentChapter}-{currentSubChapter} (Attempt {attempt}) generated: ~{word_count} words.")

                    # Word Count Check
                    if regenOnLowWords and word_count < min_words_sub:
                        if attempt < MAX_GENERATION_ATTEMPTS: print(f"    Word count ({word_count}) < min ({min_words_sub}). Regenerating..."); sleep(waitTime); attempt += 1; continue
                        else: print(f"    Word count still low after {MAX_GENERATION_ATTEMPTS} attempts. Keeping.")

                    # Save & Update Context
                    # *** MODIFIED CONTEXT UPDATE ***
                    lastGeneratedSubchapter_Full = generated_text # Store full text
                    current_chapter_content_parts.append(generated_text)
                    totalGeneratedWords += word_count
                    writeToFile(full_path, split_string_into_chunks(generated_text, 150) + "\n")
                    print(f"  Sub-Chapter {currentChapter}-{currentSubChapter} finished.")
                    sub_chapter_generated_successfully = True
                    sleep(waitTime)
                if not sub_chapter_generated_successfully: print(f"  FAILED to generate Sub-Chapter {currentChapter}-{currentSubChapter}.")
            # *** MODIFIED CONTEXT UPDATE ***
            lastGeneratedChapter_Full = "\n\n".join(current_chapter_content_parts) # Update full chapter context

        else:
            # --- Full Chapter Generation (No Sub-Chapters) ---
            target_words_chap = int(wordsPerChapter_gen) # Use adjusted
            min_words_chap = int(target_words_chap * (1 - target_word_count_tolerance))
            chapter_generated_successfully = False
            attempt = 1

            while attempt <= MAX_GENERATION_ATTEMPTS and not chapter_generated_successfully:
                print(f"  Generating Chapter {currentChapter} (Attempt {attempt}/{MAX_GENERATION_ATTEMPTS})...")
                # *** MODIFIED CALL ***
                prompt = generatePrompt(2, I_bookName, I_bookGenre, I_numberOfChapters,
                                        I_bookBrief, combinedChapterDetails,
                                        wordsPerChapter_gen, 0, # Adjusted words
                                        G_bookOutline, 0,
                                        "", # No sub-chapter context
                                        lastGeneratedChapter_Full, # Full context of PREVIOUS chapter
                                        currentChapter, 0,
                                        character_bios=I_characterBios, # Added
                                        world_notes=I_worldNotes)      # Added

                response = getResponse(I_apiKey, prompt)
                # ... (Keep existing error handling, quota check, retry logic for chapters) ...
                if response == QUOTA_EXCEEDED_ERROR_STRING:
                     if not handle_quota_error(): sys.exit(1)
                     continue
                elif response.startswith("API Error:") or response.startswith("Error parsing") or response.startswith("Request failed:") or response.startswith("Unexpected Error:") or response.startswith("API Warning:"):
                    print(f"  Error/Warning generating chapter {currentChapter} (Attempt {attempt}): {response}")
                    if attempt == MAX_GENERATION_ATTEMPTS: print(f"  Max attempts reached for chapter {currentChapter}. Skipping."); writeToFile(full_path, f"\n\n!! ERROR: CHAPTER {currentChapter} !!\n{response}\n")
                    else: print(f"  Waiting {waitTime*2}s before retry..."); sleep(waitTime * 2)
                    attempt += 1; continue

                generated_text = response
                word_count = len(generated_text.split())
                print(f"  Chapter {currentChapter} (Attempt {attempt}) generated: ~{word_count} words.")

                # Word Count Check
                if regenOnLowWords and word_count < min_words_chap:
                    if attempt < MAX_GENERATION_ATTEMPTS: print(f"  Word count ({word_count}) < min ({min_words_chap}). Regenerating..."); sleep(waitTime); attempt += 1; continue
                    else: print(f"  Word count still low after {MAX_GENERATION_ATTEMPTS} attempts. Keeping.")

                # Save & Update Context
                # *** MODIFIED CONTEXT UPDATE ***
                lastGeneratedChapter_Full = generated_text # Store full text for NEXT chapter's context
                totalGeneratedWords += word_count
                writeToFile(full_path, split_string_into_chunks(generated_text, 150) + "\n")
                print(f"  Chapter {currentChapter} finished.")
                chapter_generated_successfully = True
                sleep(waitTime)
            if not chapter_generated_successfully: print(f"  FAILED to generate Chapter {currentChapter}.")

    # ----- Final Summary -----
    print("\n----- Generation Complete! -----")
    print(f"Book '{I_bookName}' generation process finished.")
    print(f"Total approximate words generated: {totalGeneratedWords}")
    print(f"Output saved to: {full_path}")
    print("\nRecommendation: Please review the generated content for flow, consistency, and accuracy.")
    print("Manual editing will likely be required to refine the text.")

# Main execution block
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n--- Generation Interrupted By User ---")
        print(f"Partial content may have been saved to '{full_path}'.")
        sys.exit(1)
    except Exception as e:
        # Catch any unexpected errors in main that weren't caught elsewhere
        print("\n----- An Unexpected Error Occurred During Execution -----")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Details: {e}")
        print("Traceback:")
        traceback.print_exc()
        print("----------------------------------------------------------")
        print(f"Partial content may have been saved to '{full_path}'.")
        sys.exit(1)
