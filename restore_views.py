import os

def restore():
    path = 'main/views.py'
    if not os.path.exists(path):
        print("File not found")
        return

    with open(path, 'rb') as f:
        data = f.read()
    
    # 1. We'll identify the lines that need fixing by content
    # Use ASCII constants only
    lines = data.split(b'\n')
    new_lines = []
    
    # Replacement for the text_content logic
    replacement_content = b'        text_content = text_content.replace("<li>", "\\n- ").replace("</li>", "")'
    # Replacement for startswith
    replacement_startswith = b"            if p_text.startswith(('-', '*', '- ')) or re.match(r'^\\d+\\.', p_text):"
    
    fixed_count = 0
    for line in lines:
        l_stripped = line.strip()
        # Look for the broken replace line (any version of it)
        if b"text_content.replace" in l_stripped and b"<li>" in l_stripped:
            new_lines.append(replacement_content)
            fixed_count += 1
            print(f"Fixed content line {fixed_count}")
        elif b"p_text.startswith" in l_stripped:
            new_lines.append(replacement_startswith)
            print("Fixed startswith line")
        else:
            new_lines.append(line)
            
    with open(path, 'wb') as f:
        f.write(b'\n'.join(new_lines))
    print("Restore complete.")

if __name__ == '__main__':
    restore()
