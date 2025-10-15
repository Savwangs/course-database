import re
import json

def parse_course_sections(file_content, course_name):
    """
    Parse course sections from unstructured text file.
    Returns a list of section dictionaries.
    """
    sections = []
    
    course_blocks = re.split(r'\n(?=[A-Za-z]+\s+[\dC]+\s+sections:)', file_content)
    
    for block in course_blocks:
        if not block.strip():
            continue
            
        header_match = re.search(r'^([A-Za-z\-]+)\s+([\dC]+)\s+sections:', block, re.IGNORECASE)
        if not header_match:
            continue
        
        course_prefix = header_match.group(1).upper().replace(' ', '')
        course_number = header_match.group(2)
        
        if course_prefix == "PHYSICS":
            course_prefix = "PHYS"
        
        course_code = f"{course_prefix}-{course_number}"
        
        print(f"  Parsing course: {course_code}")
        
        title_match = re.search(rf'{re.escape(course_code)}\s+-\s+([^\n]+)', block)
        if not title_match and course_prefix == "PHYS":
            title_match = re.search(rf'PHYSICS-{course_number}\s+-\s+([^\n]+)', block)
        course_title = title_match.group(1).strip() if title_match else ""
        
        prereq_match = re.search(r'Prerequisite[s]?:\s*([^\n]+?)(?:\s+(?:Advisory|Co-requisite|Note):|$)', block, re.IGNORECASE)
        prerequisites = prereq_match.group(1).strip() if prereq_match else None
        
        section_pattern = r'(\d{4})\s+' + re.escape(course_code) + r'\s+-\s+([^\n]+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+-\s+(\d{1,2}/\d{1,2}/\d{4})'
        section_matches = list(re.finditer(section_pattern, block))
        
        if not section_matches:
            print(f"    No sections found with pattern for {course_code}")
            sample_match = re.search(r'(\d{4})\s+([A-Z\-]+\d+)\s+-', block)
            if sample_match:
                print(f"    Found sample section format: {sample_match.group(2)}")
        
        if not section_matches and course_prefix == "PHYS":
            alt_pattern = r'(\d{4})\s+PHYS-' + course_number + r'\s+-\s+([^\n]+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+-\s+(\d{1,2}/\d{1,2}/\d{4})'
            section_matches = list(re.finditer(alt_pattern, block))
            if section_matches:
                print(f"    Found sections with PHYS- prefix")
        
        for i, match in enumerate(section_matches):
            section_num = match.group(1)
            title = match.group(2).strip()
            
            start_pos = match.end()
            end_pos = section_matches[i + 1].start() if i + 1 < len(section_matches) else len(block)
            section_content = block[start_pos:end_pos]
            
            instructor_match = re.search(r'[\d.]+\s+([^\n]+?)\s+(?:Prerequisite|Note:|Open|Clsd)', section_content)
            instructor = instructor_match.group(1).strip() if instructor_match else "Staff"
            
            meeting_lines = []
            
            meeting_pattern = r'([MTWF][a-z]*(?:\s+[MTWF][a-z]*)*)\s+(\d{1,2}:\d{2}[AP]M)\s+-\s+(\d{1,2}:\d{2}[AP]M)\s+([A-Z]+)\s+([A-Z0-9\-]+)'
            meeting_matches = re.findall(meeting_pattern, section_content)
            
            for m in meeting_matches:
                days = m[0].strip()
                start_time = m[1]
                end_time = m[2]
                building = m[3]
                room = m[4]
                
                meeting_lines.append({
                    'days': days,
                    'time': f"{start_time} - {end_time}",
                    'room': f"{building} {room}",
                    'format': 'in-person'
                })
            
            if 'OFF' in section_content and 'ONLINE' in section_content:
                if re.search(r'OFF\s+PART-ONL', section_content):
                    hybrid_meeting = re.search(r'([MTWF][a-z]*(?:\s+[MTWF][a-z]*)*)\s+(\d{1,2}:\d{2}[AP]M)\s+-\s+(\d{1,2}:\d{2}[AP]M)', section_content)
                    if hybrid_meeting:
                        for meeting in meeting_lines:
                            meeting['format'] = 'hybrid'
                    else:
                        meeting_lines.append({
                            'days': 'See comments',
                            'time': 'See comments',
                            'room': 'Online/On-campus',
                            'format': 'hybrid'
                        })
                else:
                    # Fully online
                    meeting_lines = [{
                        'days': 'Online',
                        'time': 'Asynchronous',
                        'room': 'Online',
                        'format': 'online'
                    }]
            elif 'OFF' in section_content and 'PART-ONL' in section_content:
                for meeting in meeting_lines:
                    meeting['format'] = 'hybrid'
                
                if not meeting_lines:
                    meeting_lines.append({
                        'days': 'See comments',
                        'time': 'See comments',
                        'room': 'Online/On-campus',
                        'format': 'hybrid'
                    })
            
            if not meeting_lines:
                if 'NEED RM' in section_content or re.search(r'[A-Z]{2,}\s+\d+', section_content):
                    meeting_lines.append({
                        'days': 'TBA',
                        'time': 'TBA',
                        'room': 'TBA',
                        'format': 'in-person'
                    })
            
            section_data = {
                'course_code': course_code,
                'course_title': title,
                'section_number': section_num,
                'instructor': instructor,
                'meetings': meeting_lines,
                'status': 'Open, Seats Available'
            }
            
            if prerequisites:
                section_data['prerequisites'] = prerequisites
            
            sections.append(section_data)
    
    return sections


def main():
    files = {
        'BIOSC': ['BIOSC.txt', 'biosc.txt'],
        'CHEM': ['CHEM.txt', 'chem.txt'],
        'ENGL': ['ENGL.txt', 'engl.txt'],
        'PHYS': ['PHYS.txt', 'phys.txt'],
        'MATH': ['MATH.txt', 'math.txt'],
        'COMSC': ['COMSC.txt', 'comsc.txt']
    }
    
    all_courses = {}
    
    for file_key, file_paths in files.items():
        found = False
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    print(f"Processing {file_path}...")
                    sections = parse_course_sections(content, file_key)
                    print(f"  Found {len(sections)} sections")
                    
                    for section in sections:
                        course_code = section['course_code']
                        if course_code not in all_courses:
                            all_courses[course_code] = {
                                'course_code': course_code,
                                'course_title': section['course_title'],
                                'sections': []
                            }
                            if 'prerequisites' in section:
                                all_courses[course_code]['prerequisites'] = section['prerequisites']
                        
                        all_courses[course_code]['sections'].append({
                            'section_number': section['section_number'],
                            'instructor': section['instructor'],
                            'meetings': section['meetings'],
                            'status': section['status']
                        })
                    found = True
                    break
            except FileNotFoundError:
                continue
        
        if not found:
            print(f"Warning: No file found for {file_key}. Tried: {', '.join(file_paths)}")
    
    if 'ENGL-C1000' in all_courses:
        all_courses['ENGL-C1000']['equivalent_courses'] = []
        
        if 'ENGL-C1000E' in all_courses:
            all_courses['ENGL-C1000']['equivalent_courses'].append({
                'course_code': 'ENGL-C1000E',
                'course_title': all_courses['ENGL-C1000E']['course_title'],
                'sections': all_courses['ENGL-C1000E']['sections']
            })
            if 'prerequisites' in all_courses['ENGL-C1000E']:
                all_courses['ENGL-C1000']['equivalent_courses'][-1]['prerequisites'] = all_courses['ENGL-C1000E']['prerequisites']
        
        if 'ENGL-122AL' in all_courses:
            all_courses['ENGL-C1000']['equivalent_courses'].append({
                'course_code': 'ENGL-122AL',
                'course_title': all_courses['ENGL-122AL']['course_title'],
                'sections': all_courses['ENGL-122AL']['sections']
            })
            if 'prerequisites' in all_courses['ENGL-122AL']:
                all_courses['ENGL-C1000']['equivalent_courses'][-1]['prerequisites'] = all_courses['ENGL-122AL']['prerequisites']
    
    if 'ENGL-123' in all_courses:
        all_courses['ENGL-123']['equivalent_courses'] = []
        
        if 'ENGL-126A' in all_courses:
            all_courses['ENGL-123']['equivalent_courses'].append({
                'course_code': 'ENGL-126A',
                'course_title': all_courses['ENGL-126A']['course_title'],
                'sections': all_courses['ENGL-126A']['sections']
            })
            if 'prerequisites' in all_courses['ENGL-126A']:
                all_courses['ENGL-123']['equivalent_courses'][-1]['prerequisites'] = all_courses['ENGL-126A']['prerequisites']
        
        if 'ENGL-C1001' in all_courses:
            all_courses['ENGL-123']['equivalent_courses'].append({
                'course_code': 'ENGL-C1001',
                'course_title': all_courses['ENGL-C1001']['course_title'],
                'sections': all_courses['ENGL-C1001']['sections']
            })
            if 'prerequisites' in all_courses['ENGL-C1001']:
                all_courses['ENGL-123']['equivalent_courses'][-1]['prerequisites'] = all_courses['ENGL-C1001']['prerequisites']
    
    courses_list = list(all_courses.values())
    
    with open('courses_data.json', 'w', encoding='utf-8') as f:
        json.dump(courses_list, f, indent=2, ensure_ascii=False)
    
    print(f"Successfully extracted {len(courses_list)} courses")
    print("Output saved to: courses_data.json")


if __name__ == "__main__":
    main()