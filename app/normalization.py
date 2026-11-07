"""Vehicle identifiers shared by API adapters."""
import re

def text(v): return str(v).strip() if v is not None else ""

def vehicle(v):
    s=text(v).upper().replace(' ','')
    if re.fullmatch(r'[A-ZА-Я]\d{3}[A-ZА-Я]{2}\d{2,3}',s):
        return s.translate(str.maketrans('ABEKMHOPCTYX','АВЕКМНОРСТУХ'))
    return text(v)
