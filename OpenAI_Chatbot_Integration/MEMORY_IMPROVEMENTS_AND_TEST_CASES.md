# Conversation Memory System - Improvements & Test Cases

## 🔧 **Part 1: Memory System Improvements**

The current system is **good**, but here are **5 enhancements** that would make follow-up questions even more accurate:

---

### **1. Extract & Store Key Entities from Previous Responses**

**Current:** Passes raw conversation history to LLM  
**Improvement:** Extract structured entities (course codes, filters) from each exchange

```python
# Add to session:
session['last_mentioned'] = {
    'course_codes': ['COMSC-110'],
    'subjects': ['COMSC'],
    'filters': {'mode': 'online', 'day': 'M'},
    'instructors': ['Strickland, Joanne']
}

# When user says "What about evening?", use last_mentioned directly
```

**Benefit:** More reliable context without relying on LLM reinterpretation

---

### **2. Implement Pronoun Resolution**

**Current:** LLM tries to resolve "that course", "it", "those sections"  
**Improvement:** Explicit pronoun mapping before LLM parsing

```python
# Pronoun resolution
pronouns_map = {
    'that course': last_mentioned_course,
    'it': last_mentioned_course,
    'those sections': last_mentioned_sections,
    'this class': last_mentioned_course,
    'them': last_mentioned_sections
}

# Replace pronouns before parsing
resolved_query = replace_pronouns(user_query, pronouns_map)
```

**Benefit:** Eliminates ambiguity, faster parsing

---

### **3. Add Conversation Context Window Optimization**

**Current:** Sends last 10 messages (could be 5 exchanges)  
**Improvement:** Smart summarization of older messages

```python
# Keep recent messages verbatim
recent_messages = conversation_history[-6:]  # Last 3 exchanges

# Summarize older context
if len(conversation_history) > 6:
    summary = {
        'role': 'system',
        'content': f"Earlier in this conversation, user asked about: {summarize_older_context()}"
    }
    messages = [system_message, summary] + recent_messages
```

**Benefit:** Better context with lower token usage

---

### **4. Add Intent Persistence Across Turns**

**Current:** Each query reparses intent  
**Improvement:** Track conversation intent/topic

```python
# Track conversation flow
session['conversation_flow'] = {
    'topic': 'finding_sections',  # vs 'prerequisites', 'instructor_info'
    'primary_course': 'COMSC-110',
    'refinement_stage': 'filtering'  # initial -> refining -> comparing
}

# Use to interpret vague follow-ups
if user_query == "What else?" and topic == 'finding_sections':
    # Show other available sections
```

**Benefit:** Handles vague questions like "What else?", "Tell me more"

---

### **5. Implement Clarification Prompts**

**Current:** Best-guess interpretation  
**Improvement:** Ask for clarification when ambiguous

```python
# Detect ambiguity
if confidence_score < 0.7:
    return {
        'type': 'clarification',
        'message': "I'm not sure if you're asking about:\n1) Online sections\n2) Evening times\nWhich would you like?"
    }
```

**Benefit:** Reduces incorrect interpretations

---

## 📊 **Should You Implement These?**

**My Recommendation:** Your current system is **80% there**. These improvements would get you to **95%**, but require:
- More complexity (entity tracking)
- Additional session storage
- More backend logic

**For an MVP/college project:** Current implementation is excellent!  
**For production at scale:** Implement improvements 1-3.

---

---

# 🧪 **Part 2: Comprehensive Test Cases**

Based on your **actual database** (Full_STEM_DataBase.json), here are **10 realistic test scenarios** covering the full spectrum of student course scheduling needs.

---

## **Test Case 1: Basic Course Discovery → Filtering → Instructor**

**Scenario:** Student exploring intro CS course options

### **Initial Query:**
```
"Show me COMSC-110 sections"
```

**Expected Response:**
- Found 3 sections for COMSC-110
- Lists:
  - Section 9024 (Strickland, Joanne) - Online, Asynchronous - **Open**
  - Section 8292 (Youn, Steve) - Hybrid, T Th 6:30-7:55 PM - **Open**
  - Section 5657 (Aladegbami, Kemi) - Online, Asynchronous - **Open**

---

### **Follow-Up 1:**
```
"Online only"
```

**Expected Response:**
- For those COMSC-110 sections, here are the online ones:
- Section 9024 (Strickland, Joanne)
- Section 5657 (Aladegbami, Kemi)

---

### **Follow-Up 2:**
```
"Who teaches it?"
```

**Expected Response:**
- For COMSC-110 online sections, the instructors are:
  - Joanne Strickland
  - Kemi Aladegbami

---

### **Follow-Up 3:**
```
"What are the prerequisites?"
```

**Expected Response:**
- COMSC-110 prerequisites: Placement as determined by the college's multiple measures assessment process or completion of a course taught at or above the level of intermediate algebra.

---

### **Follow-Up 4:**
```
"Show me Joanne Strickland's sections"
```

**Expected Response:**
- For COMSC-110 taught by Joanne Strickland:
  - Section 9024: Online, Asynchronous - **Open**

---

## **Test Case 2: Subject Exploration → Time Filtering → Day Filtering**

**Scenario:** Student looking for morning math classes

### **Initial Query:**
```
"Show me MATH classes on Monday mornings"
```

**Expected Response:**
- Found X sections across multiple MATH courses (Monday, morning)
- Lists courses like MATH-191L, MATH-195, etc. with Monday morning times

---

### **Follow-Up 1:**
```
"Just Calc 1"
```

**Expected Response:**
- For MATH-192 (Calculus I) on Monday mornings:
  - Section 9300 (Staff, SRC): M W 11:25 AM - 1:55 PM - **Open**

---

### **Follow-Up 2:**
```
"What about Wednesday instead?"
```

**Expected Response:**
- For MATH-192 sections on Wednesday mornings:
  - [Same section since it meets M W]
  - Section 9300: M W 11:25 AM - 1:55 PM

---

### **Follow-Up 3:**
```
"Any in the afternoon?"
```

**Expected Response:**
- For MATH-192 sections in the afternoon:
  - Section 9281: [Shows afternoon sections]

---

### **Follow-Up 4:**
```
"Is Calc 2 available?"
```

**Expected Response:**
- Found X sections for MATH-193 (Analytic Geometry and Calculus II)
  - Lists available MATH-193 sections

---

## **Test Case 3: Prerequisites Chain → Course Sequence**

**Scenario:** Student planning CS major path

### **Initial Query:**
```
"What are the prerequisites for COMSC-200?"
```

**Expected Response:**
- **COMSC-200: Data Structures**
- Prerequisites: COMSC-165 or equivalent

---

### **Follow-Up 1:**
```
"What about COMSC-165?"
```

**Expected Response:**
- **COMSC-165: [Course Title]**
- Prerequisites: COMSC-110 or ENGIN-135 or equivalent

---

### **Follow-Up 2:**
```
"Is COMSC-110 offered?"
```

**Expected Response:**
- Found 3 sections for COMSC-110
  - [Lists sections]

---

### **Follow-Up 3:**
```
"Can I take 165 and 200 together?"
```

**Expected Response:**
- COMSC-200 requires COMSC-165 as a prerequisite, so you must complete COMSC-165 first before enrolling in COMSC-200.

---

### **Follow-Up 4:**
```
"Show me all available COMSC courses"
```

**Expected Response:**
- Here are the available COMSC courses:
  - COMSC-101, COMSC-110, COMSC-140, COMSC-156, COMSC-165, COMSC-171, COMSC-175, COMSC-200, COMSC-210, COMSC-255, COMSC-260

---

## **Test Case 4: Format Filtering → Status Check → Instructor Search**

**Scenario:** Student needs online classes due to work schedule

### **Initial Query:**
```
"Show me online BIOSC courses"
```

**Expected Response:**
- Found X online sections across BIOSC courses
- Lists:
  - BIOSC-101 sections (online asynchronous)
  - [Other online BIOSC courses]

---

### **Follow-Up 1:**
```
"Just the ones with labs"
```

**Expected Response:**
- For online BIOSC courses with labs:
  - BIOSC-102 sections (some hybrid with online + in-person lab)

---

### **Follow-Up 2:**
```
"Are any fully asynchronous?"
```

**Expected Response:**
- For fully asynchronous BIOSC courses:
  - BIOSC-101 sections 5039, 5037 (Ensign, Caitlin)

---

### **Follow-Up 3:**
```
"Who is Caitlin Ensign?"
```

**Expected Response:**
- Caitlin Ensign teaches BIOSC-101 sections:
  - Section 5039: Online, Asynchronous
  - Section 5037: Online, Asynchronous

---

### **Follow-Up 4:**
```
"Any waitlisted?"
```

**Expected Response:**
- [Checks status field]
- All BIOSC-101 sections are currently **Open** (no waitlisted sections)

---

## **Test Case 5: Evening Classes → Hybrid Format → Specific Days**

**Scenario:** Working student needs evening classes

### **Initial Query:**
```
"Show me evening CHEM classes"
```

**Expected Response:**
- Found X CHEM sections in the evening (5:00 PM and later)
- Lists evening CHEM sections

---

### **Follow-Up 1:**
```
"Just Tuesday and Thursday"
```

**Expected Response:**
- For CHEM courses on Tuesday/Thursday evenings:
  - [Lists T Th evening sections]

---

### **Follow-Up 2:**
```
"Are any hybrid?"
```

**Expected Response:**
- For hybrid CHEM courses on Tuesday/Thursday evenings:
  - [Lists hybrid sections if available, or states none found]

---

### **Follow-Up 3:**
```
"What's the difference between CHEM-120 and CHEM-121?"
```

**Expected Response:**
- **CHEM-120:** [Course Title]
  - Prerequisites: [Lists prereqs]
- **CHEM-121:** [Course Title]
  - Prerequisites: CHEM-120 or equivalent
  - Note: CHEM-121 is typically the second semester after CHEM-120

---

### **Follow-Up 4:**
```
"Show me CHEM-120 only"
```

**Expected Response:**
- Found X sections for CHEM-120
  - [Lists CHEM-120 sections]

---

## **Test Case 6: Physics Major Sequence → Lab Coordination**

**Scenario:** Engineering student planning physics sequence

### **Initial Query:**
```
"Show me PHYS-120 sections"
```

**Expected Response:**
- Found 2 sections for PHYS-120 (General College Physics I)
- Section 8055 (Kisseleva-Eggleton, Ludmila):
  - Lecture: T Th 12:45-2:10 PM
  - Lab: M 2:30-5:20 PM
  - Discussion: Th 4:05-5:20 PM
- Section 8054 (Goldenberg, Steven):
  - [Lists meetings]

---

### **Follow-Up 1:**
```
"Does it have a lab?"
```

**Expected Response:**
- Yes, PHYS-120 includes lab components:
  - Section 8055: Lab on Mondays 2:30-5:20 PM
  - Section 8054: Lab on Tuesdays 2:30-5:20 PM

---

### **Follow-Up 2:**
```
"What times are the labs?"
```

**Expected Response:**
- PHYS-120 lab times:
  - Section 8055: Monday 2:30-5:20 PM (afternoon)
  - Section 8054: Tuesday 2:30-5:20 PM (afternoon)

---

### **Follow-Up 3:**
```
"Can I avoid afternoon labs?"
```

**Expected Response:**
- Both PHYS-120 sections have afternoon labs (2:30 PM). There are no morning or evening lab options currently available.

---

### **Follow-Up 4:**
```
"What comes after PHYS-120?"
```

**Expected Response:**
- After PHYS-120, the typical sequence is:
  - **PHYS-121:** General College Physics II
  - Prerequisites for PHYS-121: PHYS-120 or equivalent

---

## **Test Case 7: Math Pathway → Support Courses → Placement**

**Scenario:** Student unsure about math placement

### **Initial Query:**
```
"Show me Pre-Calculus courses"
```

**Expected Response:**
- Found sections for MATH-191 (Pre-Calculus)
- Also available: MATH-191L (Pre-Calculus with Support)

---

### **Follow-Up 1:**
```
"What's the difference between 191 and 191L?"
```

**Expected Response:**
- **MATH-191:** Pre-Calculus (5 units)
- **MATH-191L:** Pre-Calculus with Support (6 units)
  - 191L includes additional support instruction for students who may need extra help
  - Covers the same material but with extended class time

---

### **Follow-Up 2:**
```
"Which one should I take?"
```

**Expected Response:**
- The choice depends on your math background:
  - **MATH-191:** If you're comfortable with algebra and feel prepared
  - **MATH-191L:** If you want extra support and more class time to master the material
- Both have the same prerequisite: Placement as determined by the college's multiple measures assessment

---

### **Follow-Up 3:**
```
"Show me 191L sections"
```

**Expected Response:**
- Found 2 sections for MATH-191L
  - Section 2943 (Wylie, Lindsay): M W 11:10 AM - 2:20 PM
  - Section 2110: [Details]

---

### **Follow-Up 4:**
```
"What can I take after Pre-Calc?"
```

**Expected Response:**
- After MATH-191 (or 191L), you can take:
  - **MATH-192:** Analytic Geometry and Calculus I
  - This is the standard calculus sequence for STEM majors

---

## **Test Case 8: Multi-Course Comparison → Schedule Building**

**Scenario:** Student building a full semester schedule

### **Initial Query:**
```
"Show me COMSC-110 and MATH-192 on Monday/Wednesday"
```

**Expected Response:**
- Found sections for COMSC-110 and MATH-192 on Monday/Wednesday:

**COMSC-110:**
- [Lists M W or M W F sections if available, likely shows online or hybrid]

**MATH-192:**
- Section 9300: M W 11:25 AM - 1:55 PM

---

### **Follow-Up 1:**
```
"Do those time slots conflict?"
```

**Expected Response:**
- Let me check the schedules:
  - COMSC-110 online sections don't have fixed meeting times
  - MATH-192 section 9300: M W 11:25 AM - 1:55 PM
  - No conflicts if you choose online COMSC-110!

---

### **Follow-Up 2:**
```
"Add PHYS-110 to my search"
```

**Expected Response:**
- Found sections for PHYS-110 (Elementary Physics):
  - Section 1208: M W 8:00-9:25 AM + M W 9:35-11:00 AM
  - Section 1207: T Th 11:10 AM-12:35 PM + T Th 12:45-2:10 PM

---

### **Follow-Up 3:**
```
"Can I take all three without conflicts?"
```

**Expected Response:**
- Here's a possible schedule:
  - **PHYS-110 (Section 1208):** M W 8:00-11:00 AM
  - **MATH-192 (Section 9300):** M W 11:25 AM - 1:55 PM
  - **COMSC-110:** Online (asynchronous, no fixed time)
  - ✅ No conflicts! All three fit on Monday/Wednesday

---

### **Follow-Up 4:**
```
"Show me open sections only"
```

**Expected Response:**
- Filtering for open sections only:
  - [Re-lists only sections with status: "Open"]

---

## **Test Case 9: Instructor Preference → Rating/Experience**

**Scenario:** Student researching specific instructors

### **Initial Query:**
```
"Who teaches MATH-193?"
```

**Expected Response:**
- MATH-193 (Analytic Geometry and Calculus II) is taught by:
  - Staff, SRC (Section 9292)
  - [Other instructors if available]

---

### **Follow-Up 1:**
```
"Are there any other math instructors?"
```

**Expected Response:**
- Other MATH instructors in the database:
  - Pineda-Carranza, Servando (MATH-191)
  - Wylie, Lindsay (MATH-191L)
  - Gomez, Concha (MATH-194)
  - [Lists unique instructors across all MATH courses]

---

### **Follow-Up 2:**
```
"Show me all courses taught by Gomez"
```

**Expected Response:**
- Courses taught by Concha Gomez:
  - **MATH-194** (Linear Algebra) - Section 8242

---

### **Follow-Up 3:**
```
"What's MATH-194?"
```

**Expected Response:**
- **MATH-194: Linear Algebra**
  - Prerequisites: MATH-193 or equivalent
  - Available section: 8242 (Gomez, Concha) - Hybrid format

---

### **Follow-Up 4:**
```
"When does that section meet?"
```

**Expected Response:**
- MATH-194 Section 8242 (Gomez, Concha):
  - Format: Hybrid
  - In-person meetings: Thursdays 5:30-7:30 PM (exams: 2/26, 3/19, 4/30, and final 5/21)
  - Other instruction online via Canvas

---

## **Test Case 10: Status Check → Waitlist → Alternative Options**

**Scenario:** Student dealing with closed/waitlisted courses

### **Initial Query:**
```
"Show me open COMSC-200 sections"
```

**Expected Response:**
- [If COMSC-200 not in database:]
- I couldn't find COMSC-200 in the current database. 
- Would you like to see:
  - Related COMSC courses?
  - Prerequisites for COMSC-200?

---

### **Follow-Up 1:**
```
"Show me all COMSC courses that are open"
```

**Expected Response:**
- Here are open COMSC courses:
  - COMSC-101, COMSC-110, COMSC-140, COMSC-156, COMSC-165, COMSC-171, COMSC-175, COMSC-210, COMSC-255, COMSC-260
  - [Lists sections with status: "Open"]

---

### **Follow-Up 2:**
```
"What if I'm on a waitlist?"
```

**Expected Response:**
- Waitlist information:
  - If a section shows "Waitlist" status, you can add yourself to the waitlist
  - Your position on the waitlist determines your chances of getting in
  - Contact the instructor or department for waitlist movement updates

---

### **Follow-Up 3:**
```
"Show me alternative CS courses"
```

**Expected Response:**
- Alternative COMSC courses currently open:
  - **COMSC-140:** [Details]
  - **COMSC-156:** [Details]
  - **COMSC-171:** [Details]

---

### **Follow-Up 4:**
```
"Which one is easiest to get into?"
```

**Expected Response:**
- Based on availability:
  - All listed COMSC courses show "Open" status
  - COMSC-110 has the most sections (3 open sections)
  - Your choice should be based on prerequisites and your academic goals

---

---

## 📋 **Test Case Coverage Summary**

| Test Case | Coverage |
|-----------|----------|
| **1. Basic Course Discovery** | Course search, filtering by format, instructor lookup, prerequisites |
| **2. Subject Exploration** | Subject-level search, time/day filtering, course refinement |
| **3. Prerequisites Chain** | Multi-course prerequisites, course sequencing, degree planning |
| **4. Format Filtering** | Online/hybrid/in-person, status checking, instructor details |
| **5. Evening Classes** | Time-specific search, format + day combination, course comparison |
| **6. Physics Major Sequence** | Lab coordination, multi-meeting sections, course sequences |
| **7. Math Pathway** | Support courses, course differences, placement guidance |
| **8. Multi-Course Comparison** | Schedule building, conflict checking, multiple course search |
| **9. Instructor Preference** | Instructor search, cross-course instructor lookup, section details |
| **10. Status Check** | Waitlist handling, alternatives, availability checking |

---

## ✅ **How to Use These Test Cases**

### **For Manual Testing:**
1. Start Flask server
2. Open chatbot
3. Work through each test case sequentially
4. Verify responses match expected outputs
5. Check conversation badge updates correctly

### **For Automated Testing (Future):**
```python
def test_case_1():
    # Clear conversation
    clear_conversation()
    
    # Initial query
    response1 = ask("Show me COMSC-110 sections")
    assert "Found 3 sections" in response1
    assert "Strickland, Joanne" in response1
    
    # Follow-up 1
    response2 = ask("Online only")
    assert "online" in response2.lower()
    assert len(extract_sections(response2)) == 2
    
    # ... continue testing
```

---

## 🎯 **Expected Success Criteria**

Your memory system should achieve:

✅ **90%+ accuracy** on follow-up questions  
✅ **< 2 seconds** response time per query  
✅ **Zero errors** on pronoun resolution ("it", "that", "those")  
✅ **Correct counts** in summary lines  
✅ **Context persistence** across 5+ turn conversations  

---

## 🚀 **Next Steps**

1. **Run all 10 test cases** manually
2. **Document any failures** or unexpected behaviors
3. **Prioritize fixes** based on frequency of issues
4. **Consider implementing** memory improvements 1-3 if issues persist
5. **Create regression tests** for critical paths

---

Built to ensure your chatbot handles real student course scheduling scenarios! 🎓✨

