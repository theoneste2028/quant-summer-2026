"""Extract the page number of each contents entry from a rendered PDF."""
import json, re, sys
import pymupdf

pdf, entries_json, out = sys.argv[1], sys.argv[2], sys.argv[3]
entries = json.load(open(entries_json))

doc = pymupdf.open(pdf)
# Page text per page, normalised for the dashes and spacing PDF extraction adds.
pages = []
for p in doc:
    t = p.get_text()
    t = t.replace("—", "—").replace("–", "—")
    t = re.sub(r"[ \t]+", " ", t)
    pages.append(t)

# Identify contents pages by density: a page listing many entry titles is part
# of the table of contents, not the body. Hard-coding "skip page 2" broke once
# the contents grew onto a second page.
# Each entry title appears exactly twice in the document: once in the contents
# and once as the heading itself. The heading is always the later of the two, so
# taking the LAST occurrence identifies it without needing to work out where the
# contents end — which is brittle, because a body page can legitimately carry as
# many headings as a contents page.

mapping = {}
missing = []
for num, title, lvl in entries:
    key = f"{num} {title}"
    hits = [i for i, t in enumerate(pages) if f"{num} {title}" in t]
    if not hits:
        hits = [i for i, t in enumerate(pages) if title in t]
    if not hits:
        missing.append(key)
    else:
        mapping[key] = hits[-1] + 1     # last occurrence = the real heading

json.dump(mapping, open(out, "w"), indent=1)
print(f"mapped {len(mapping)}/{len(entries)} entries across {doc.page_count} pages")
if missing:
    print("  UNMAPPED:", missing)
