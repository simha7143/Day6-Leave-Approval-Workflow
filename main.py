import csv
import requests
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from google import genai


# STEP 1: Read policy
policy_text = Path("Day6_Leave_Policy.txt").read_text(encoding="utf-8")


# STEP 2: Split policy into numbered sections
matches = list(
    re.finditer(r"(?m)^\s*(\d+)\.\s+.*$", policy_text)
)

sections = {}

for i, match in enumerate(matches):
    number = match.group(1)
    start = match.start()

    end = (
        matches[i + 1].start()
        if i + 1 < len(matches)
        else len(policy_text)
    )

    sections[number] = policy_text[start:end].strip()

print("Total sections found:", len(sections))


# STEP 3: Retrieve matching sections
def retrieve_sections(question):

    stopwords = {
        "can", "i", "the", "a", "an", "is", "are", "do",
        "my", "me", "to", "for", "of", "in", "on", "what",
        "how", "many", "who", "if", "does", "be", "it"
    }

    question_words = set(
        re.findall(r"\b[a-z]+\b", question.lower())
    )

    question_words -= stopwords

    scores = []

    for number, content in sections.items():

        section_words = set(
            re.findall(r"\b[a-z]+\b", content.lower())
        )

        score = len(question_words & section_words)

        if score > 0:
            scores.append((score, number, content))

    scores.sort(reverse=True)

    if scores and scores[0][0] >= 1:
        return scores[:2]

    return []


# STEP 4: Ask employee question
question = input("\nEnter employee question: ")

results = retrieve_sections(question)

if results:
    print("\nMatching policy sections:")

    for score, number, content in results:
        print(f"\nSection {number} | Score: {score}")
        print(content)

else:
    print("\nNO MATCHING SECTION")


# STEP 5: Connect Gemini API
load_dotenv()

api_key = os.environ.get("LLM_API_KEY")

if not api_key:
    print("ERROR: LLM API key not found!")
    raise SystemExit

client = genai.Client(api_key=api_key)


# STEP 6: Generate AI answer
if not results:

    draft = {
        "answer": "Not found. This topic is not covered in the leave policy.",
        "source_section": "Not found",
        "confidence": 0.0
    }

else:

    context = "\n\n".join(
        f"Section {number}:\n{content}"
        for score, number, content in results
    )

    prompt = f"""
You are an employee leave policy assistant.

Answer the employee question using ONLY the policy context.

Rules:
1. Do not invent or assume information.
2. If the policy does not answer the question, say Not found.
3. Use the correct policy section number.
4. Return valid JSON only.
5. Do not use Markdown code fences.

Required JSON format:
{{
    "answer": "Your answer",
    "source_section": "7",
    "confidence": 0.95
}}

Policy context:
{context}

Employee question:
{question}
"""

    # Generate and validate JSON
    for attempt in range(2):

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        try:

            # Remove Markdown code fences
            raw_response = response.text.strip()

            raw_response = re.sub(
                r"^```(?:json)?\s*|\s*```$",
                "",
                raw_response,
                flags=re.IGNORECASE
            ).strip()

            # Convert JSON into Python dictionary
            draft = json.loads(raw_response)

            # Check required fields
            required_fields = {
                "answer",
                "source_section",
                "confidence"
            }

            if not required_fields.issubset(draft.keys()):
                raise ValueError("Required fields are missing")

            # Check field types
            if not isinstance(draft["answer"], str):
                raise ValueError("Answer must be text")

            if not isinstance(draft["source_section"], str):
                raise ValueError("Source section must be text")

            if not isinstance(draft["confidence"], (int, float)):
                raise ValueError("Confidence must be numeric")

            if not 0 <= draft["confidence"] <= 1:
                raise ValueError("Confidence must be between 0 and 1")

            # Convert Section 7 into 7
            source = re.fullmatch(
                r"Section\s+(\d+)",
                draft["source_section"],
                flags=re.IGNORECASE
            )

            if source:
                draft["source_section"] = source.group(1)

            # Check cited section
            retrieved_numbers = [
                number for score, number, content in results
            ]

            if (
                draft["source_section"] not in retrieved_numbers
                and draft["source_section"] != "Not found"
            ):
                raise ValueError("Source section was not retrieved")

            # Valid response
            break

        except (json.JSONDecodeError, ValueError) as error:

            print("\nValidation error:", error)

            if attempt == 0:
                print("Invalid response. Retrying...")

                prompt += (
                    "\nReturn valid JSON only. "
                    "Do not include Markdown code fences."
                )

            else:
                print("ERROR: Gemini returned invalid JSON twice.")
                raise SystemExit


# STEP 7: Display AI draft
print("\n--- GEMINI AI DRAFT ---")

print(json.dumps(draft, indent=4))

response = None
webhook_url = None
# STEP 8: Human approval and API action

print("\n--- HUMAN APPROVAL REQUIRED ---")

approval = input("Approve this answer? (y/n): ").strip().lower()

if approval == "y":

    webhook_url = os.environ.get("WEBHOOK_URL")

    if not webhook_url:
        print("ERROR: Webhook URL not found in .env")

    else:
        try:
            response = requests.post(
                webhook_url,
                json=draft,
                timeout=15
            )

            print("\nAPPROVED: JSON sent to mock API.")
            print("HTTP Status:", response.status_code)

        except requests.RequestException as error:
            print("API request failed:", error)

elif approval == "n":

    print("\nRejected: nothing sent")

else:

    print("\nInvalid choice. Nothing sent.")
# STEP 9: Save test results

file_exists = Path("test_log.csv").exists()

with open("test_log.csv", "a", newline="", encoding="utf-8") as file:

    writer = csv.writer(file)

    if not file_exists:
        writer.writerow([
            "Question",
            "Source Section",
            "Confidence",
            "Approval",
            "API Status"
        ])

    api_status = (
    str(response.status_code)
    if response is not None
    else "Not sent"
)

    writer.writerow([
        question,
        draft["source_section"],
        draft["confidence"],
        approval,
        api_status
    ])

print("\nTest result saved in test_log.csv")