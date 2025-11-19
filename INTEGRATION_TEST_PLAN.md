# Integration Test Plan

## Overview
This document outlines the integration testing plan for the course database chatbot system. The goal is to validate that all system components work together correctly.

---

## 🎯 Test Plan Goals

This test plan confirms:
- ✅ Front-end and backend communication is working
- ✅ Database queries return accurate results
- ✅ LLM formatting and understanding are correct
- ✅ Logging captures user input + system responses
- ✅ Error handling is consistent
- ✅ Cross-team compatibility is validated

---

## 1. Test Environment Description

### 1.1 Tools and Technologies
- **Frontend Hosting**: **Deployed on Render at https://course-database.onrender.com/** (Document your hosting platform - e.g., Vercel, GitHub Pages, Flask)
- **Backend Framework**: Flask (Python)
- **Database**: **MongoDB(storing the user and llm interaction) and Full_STEM_DataBase.json(get all the course information from DVC course catalog)** (Document your database solution)
- **Version Control**: Git/GitHub
- **Testing Location**: **Flask local server on port 5000 and then deployed on Render** (Local development vs. staging vs. production)

### 1.2 Backend & Database Setup
- **Data Source**: 
  - DVC course catalog data located in `dvc_scraper/Full_STEM_DataBase.json`
  - UC transfer agreements in `OpenAI_Chatbot_Integration/agreements_25-26/`
- **Backend Server**: 
  - Main application: `OpenAI_Chatbot_Integration/app.py`
  - **Run this command: python3 app.py** (Document backend startup procedure)

### 1.3 Required API Keys & Environment Variables
**OpenAI API key and MongoDB Connection URL** (Document all required environment variables):
- [ ] OpenAI API Key (`OPENAI_API_KEY`)
- [ ] Other API keys (if applicable)
- [ ] Database connection strings (if applicable)
- [ ] Environment configuration (development/production)

---

## 2. Test Scenarios & Expected Results


### Test Case 2.1: Specific Course Section Query
**Objective**: Verify system returns correct sections for a specific course modality

**Steps**:
1. Open chatbot interface
2. Enter prompt: "Show me open COMSC-110 sections"
3. Submit query

**Expected Result**:
- System queries course database for COMSC-110
- Returns only in-person sections (filters out online/hybrid)
- Includes section details: instructor, days, times, room number
- All information matches source data

**Actual Result**: **Found 8 section(s) for COMSC-110 (Introduction to Programming) that are open.

COMSC-110: Introduction to Programming

HYBRID SECTIONS (includes in-person meetings)
Section 8292
Instructor: Youn, Steve
Days: T Th (in-person meetings)
Time: 6:30PM - 7:55PM
Location: NEED RM (plus PART-ONL for online component)
Units: 4.00
Notes: Partially online course with required on-campus meetings. See schedule for programming language and room. Log into Canvas on course start date.
IN-PERSON SECTIONS (fully in-person)
No in-person sections found.
ONLINE SECTIONS
Section 9024
Instructor: Strickland, Joanne
Days: Online
Time: Asynchronous
Location: ONLINE
Units: 4.00
Section 5657
Instructor: Aladegbami, Kemi
Days: Online
Time: Asynchronous
Location: ONLINE
Units: 4.00
Section 5452
Instructor: Jagpal, Rupinder
Days: Online
Time: Asynchronous
Location: ONLINE
Units: 4.00
Section 5451
Instructor: Jagpal, Rupinder
Days: Online
Time: Asynchronous
Location: ONLINE
Units: 4.00
Section 5404
Instructor: Khaja, Gene
Days: Online
Time: Asynchronous
Location: ONLINE
Units: 4.00
Section 5207
Instructor: Khaja, Gene
Days: Online
Time: Asynchronous
Location: ONLINE
Units: 4.00
Section 5523
Instructor: Amato, Nicholas
Days: Online
Time: Asynchronous
Location: ONLINE
Units: 4.00
Next steps:

Prefer a specific instructor or time? Let me know!
Want to check prerequisites? Ask for "prerequisites for COMSC-110."
Need in-person options? Say "in-person only."**

**Status**: ✅Pass

---

### Test Case 2.2: Course Prerequisite Query
**Objective**: Verify system provides accurate prerequisite information

**Steps**:
1. Open chatbot interface
2. Enter prompt: "What are the prerequisites for MATH-193?"
3. Submit query

**Expected Result**:
- System retrieves prerequisite information for MATH-192
- Response clearly lists all prerequisites
- Information matches official DVC catalog

**Actual Result**: **Prerequisites: MATH-192 or equivalent**

**Status**: ✅Pass

---

### Test Case 2.3: Invalid/Ambiguous Query
**Objective**: Test error handling for unclear user input

**Steps**:
1. Open chatbot interface
2. Enter prompt: "xyz123"
3. Submit query

**Expected Result**:
- System handles gracefully without crashing
- Returns helpful error message or asks for clarification
- User is guided to ask a valid question

**Actual Result**: **I can help you find DVC STEM courses and details and transfer from DVC agreements.

Try one of these:

"Show me open MATH-193 sections Monday morning."
"Who teaches PHYS-130 on Thursdays?"
"What are the prerequisites for COMSC-200?"
"I have completed Math 192, what does that cover at UCB?"
"What GE courses should I take at DVC for UC Berkeley?"**

**Status**: ✅Pass

---

### Test Case 2.4: Course Availability Check
**Objective**: Verify system can check if a course is offered in current semester

**Steps**:
1. Open chatbot interface
2. Enter prompt: "Can I take PHYS 130 and 230 together?"
3. Submit query

**Expected Result**:
- System searches database for PHYS-130 in Fall 2025
- Returns yes/no answer with section details if available
- If not offered, suggests alternative semesters

**Actual Result**: **❌ No - PHYS-230 requires PHYS-130 as a prerequisite, so you must complete PHYS-130 first.

PHYS-230 prerequisites: PHYS-130 or equivalent; MATH-292 (may be taken concurrently) or equivalent.

**

**Status**: ✅Pass

---

## 3. UI/UX Tests

### Test Case 3.1: Chat Bubble Display
**Objective**: Verify messages display correctly

**Steps**:
1. Open chatbot interface
2. Send a test message
3. Observe response display

**Expected Result**:
- User messages appear in distinct bubbles (typically right-aligned)
- Bot responses appear in distinct bubbles (typically left-aligned)
- Bubbles are readable and properly styled
- Text is not cut off or overlapping

**Actual Result**: **Response from the chatbot is clearly shown and displayed to the user**

**Status**: ✅Pass

---

### Test Case 3.2: Error Message Display
**Objective**: Verify error messages are user-friendly

**Steps**:
1. Trigger an error (disconnect internet, invalid input, etc.)
2. Observe error message

**Expected Result**:
- Error message is displayed clearly
- Message is user-friendly (not technical stack traces)
- User understands what went wrong
- Guidance provided on how to proceed

**Actual Result**: **❌ Unable to connect to the server. Please check your connection and try again.

Please try again or rephrase your question.**

**Status**: ✅Pass

---

### Test Case 3.3: Mobile Responsiveness
**Objective**: Verify page is usable on mobile devices

**Steps**:
1. Open chatbot on mobile device or use browser dev tools to simulate mobile
2. Test core functionality: sending messages, scrolling, reading responses
3. Check layout and button sizes

**Expected Result**:
- Page layout adapts to mobile screen size
- All text is readable without zooming
- Input field and send button are accessible
- Chat history scrolls smoothly
- No horizontal scrolling required

**Actual Result**: **Page works on mobile device and the layout is consistent**

**Status**: ✅Pass

---

### Test Case 3.4: Loading States
**Objective**: Verify loading indicators work correctly

**Steps**:
1. Submit a query
2. Observe UI while waiting for response

**Expected Result**:
- Loading indicator appears immediately after submission
- User knows the system is processing
- Send button is disabled to prevent duplicate submissions
- Loading indicator disappears when response arrives

**Actual Result**: **Shows that the chatbot is thinking or coming up with a response and the send button is disabled while the bot is thinking**

**Status**: ✅Pass

---

## 4. LLM Response Formatting Checks

### Test Case 4.1: Response Structure
**Objective**: Verify LLM responses are consistently formatted

**Steps**:
1. Ask multiple different types of questions
2. Examine response formatting

**Expected Result**:
- Responses have clear structure
- Appropriate use of headers/sections
- Consistent formatting across different query types

**Actual Result**: **Formatting is shown properly, based on the question asked by the user**

**Status**: ✅Pass

---

### Test Case 4.2: Course List Formatting
**Objective**: Verify course information is presented clearly

**Steps**:
1. Ask for a list of courses (e.g., "What COMSC courses are available?")
2. Examine how courses are displayed

**Expected Result**:
- Courses displayed in organized format (bullet points, tables, or numbered list)
- Each course includes: course code, title, and relevant details
- Format is easy to scan and read

**Actual Result**: **Format is easy to read and can see all the COMSC courses/sections**

**Status**: ✅Pass

---

## 5. Logging Requirements

### Test Case 5.1: Timestamp Logging
**Objective**: Verify all interactions are timestamped

**Steps**:
1. Send a test message
2. Check log file/database for timestamp

**Expected Result**:
- Each user query has an associated timestamp
- Each bot response has an associated timestamp
- Timestamps are in consistent format (ISO 8601 recommended)
- Timestamps are accurate to the actual interaction time

**Verification**: **All interactions are saved in MongoDB database**

**Status**: ✅Pass

---

### Test Case 5.2: User Prompt Logging
**Objective**: Verify original user prompts are saved

**Steps**:
1. Send test message: "What courses should I take for computer science?"
2. Check log file

**Expected Result**:
- Exact user prompt is saved verbatim
- No truncation or modification
- Associated with correct session/user ID

**Verification**: **Original prompts are also saved in MongoDB** (Check `user_log.json` or logging system)

**Status**: ✅Pass

---

### Test Case 5.3: Response Logging
**Objective**: Verify bot responses are saved

**Steps**:
1. Send a test query and receive response
2. Check log file

**Expected Result**:
- Complete bot response is saved
- Linked to corresponding user prompt
- Includes metadata (tokens used, model version, etc. if applicable)

**Verification**: **Responses are also logged in MongoDB** (Check `user_log.json` or logging system)

**Status**: ✅Pass

---

### Test Case 5.4: Log Data Structure
**Objective**: Verify logs are properly structured for analysis

**Steps**:
1. Review log file structure
2. Attempt to parse/analyze logs

**Expected Result**:
- Logs are in structured format (JSON recommended)
- Easy to query and analyze
- Contains all required fields: timestamp, user_input, bot_response, session_id, etc.

**Verification**: **Logs are in structured JSON format in MongoDB** 

**Status**: ✅Pass

---

## 7. Bug Report Template

### Bug Report 

**Summary**: [When the user asked for "Tuesday and Wednesday" morning sections, then the sections that were either on Tuesday or Wednesday were shown but no sections with both those days were shown]

**Severity**: ✅ Critical

**Steps to Reproduce**:
1. Make sure the LLM processes "and" by checking if both conditions are satisfied
2. Change the prompt to the LLM in the app.py file
3. Test again

**Expected Result**: 
[The bot should show only sections that have both Tuesday and Wednesday for it]

**Actual Result**: 
[Was getting all sections with either Tuesday or Wednesday]

**Resolution**: [Fixed the prompt to the LLM]

---

