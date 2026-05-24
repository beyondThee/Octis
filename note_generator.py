"""
note_generator.py
==================
Sends the full lecture transcript to Claude and gets back:
  - Organized topic-based notes
  - Flashcards (Q&A pairs)
  - A clean summary
"""

import anthropic
import config


class NoteGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-20250514"

    def generate(self, transcript):
        """
        Sends the transcript to Claude and returns a dictionary with:
          - notes
          - flashcards
          - summary

        transcript: the full lecture transcript as a string
        returns: dict with keys "notes", "flashcards", "summary"
        """

        prompt = f"""You are a helpful study assistant. Below is a transcript from a university lecture.

Please generate the following four things from this transcript:

---

1. TITLE
Write a short, clear title for this lecture (maximum 6 words). It should describe the main topic covered. Do NOT use punctuation at the end.

2. ORGANIZED NOTES
Create clear, organized notes grouped by topic. Use headings for each topic and bullet points for key concepts. Make them easy to review before an exam.

3. FLASHCARDS
Create a set of 10-20 flashcards in this exact format:
Q: [question]
A: [answer]

Focus on key terms, definitions, concepts, and important facts.

4. SUMMARY
Write a clean 1-2 paragraph summary of the entire lecture. Cover the main topics discussed and the most important takeaways.

---

Format your response EXACTLY like this (keep the headers exactly as shown):

=== TITLE ===
[your title here]

=== NOTES ===
[your notes here]

=== FLASHCARDS ===
[your flashcards here]

=== SUMMARY ===
[your summary here]

---

Here is the lecture transcript:

{transcript}
"""

        print("   Contacting Claude API...")
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = message.content[0].text

        # Parse the response into three sections
        results = self._parse_response(response_text)
        return results

    def _parse_response(self, response_text):
        results = {
            "title":      "",
            "notes":      "",
            "flashcards": "",
            "summary":    ""
        }

        try:
            remainder = response_text

            if "=== TITLE ===" in remainder:
                parts = remainder.split("=== TITLE ===")
                remainder = parts[1]
                if "=== NOTES ===" in remainder:
                    title_part, remainder = remainder.split("=== NOTES ===", 1)
                    results["title"] = title_part.strip()
                else:
                    results["title"] = remainder.strip()
                    return results
            
            if "=== NOTES ===" in remainder:
                parts = remainder.split("=== NOTES ===", 1)
                remainder = parts[1] if len(parts) > 1 else remainder

            if "=== FLASHCARDS ===" in remainder:
                notes_part, remainder = remainder.split("=== FLASHCARDS ===", 1)
                results["notes"] = notes_part.strip()

                if "=== SUMMARY ===" in remainder:
                    flashcards_part, summary_part = remainder.split("=== SUMMARY ===", 1)
                    results["flashcards"] = flashcards_part.strip()
                    results["summary"]    = summary_part.strip()
                else:
                    results["flashcards"] = remainder.strip()
            else:
                results["notes"] = remainder.strip()

        except Exception as e:
            print(f"   Note: Could not fully parse Claude's response ({e}). Saving raw output.")
            results["notes"] = response_text

        return results
