import re

def fix_views():
    path = 'main/views.py'
    with open(path, 'rb') as f:
        content = f.read()
    
    # 1. Flexible match for the corrupted block
    # We look for the part that has THE LITERAL BLOCKS of \n characters
    # PowerShell escape might have put \\n or just \n
    # Based on the error log, line 1474 contains literal \n
    
    # Use simple replacement for the most likely corrupted string
    find_str = b"text_content = re.sub(r'</?(ul|UL|li|LI)>', '', text_content)\\n        text_content = text_content.replace('<li>', '\\n  ').replace('</li>', '')\\n        for p_text in text_content.split('\\n'):"
    
    replace_str = b"""import re
        text_content = re.sub(r'</?(ul|UL|li|LI)>', '', text_content)
        text_content = text_content.replace('<li>', '\\n- ').replace('</li>', '')
        for p_text in text_content.split('\\n'):"""
        
    if find_str in content:
        content = content.replace(find_str, replace_str)
        print("Fixed primary corruption.")
    else:
        # Try a more broad regex if the spaces are different
        content = re.sub(rb"text_content = re\.sub\(r'</?\(ul\|UL\|li\|LI\)\>', '', text_content\)\\n\s+text_content = text_content\.replace\('<li>', '\\n\s+'\)\.replace\('</li>', ''\)\\n\s+for p_text in text_content\.split\('\\n'\):", 
                         replace_str, content)
        print("Tried regex replacement.")

    # Fix startswith line which has corrupted characters
    content = re.sub(rb"p_text\.startswith\(\(\'- \', \'\* \', .*\)\)", b"p_text.startswith(('-', '*', '- '))", content)

    with open(path, 'wb') as f:
        f.write(content)

if __name__ == '__main__':
    fix_views()
