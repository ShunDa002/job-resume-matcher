from pathlib import Path
from docx import Document
from reportlab.pdfgen.canvas import Canvas
from jobmatcher_resume import ResumeDocumentParser

def test_docx_paragraphs_and_tables(tmp_path):
 p=tmp_path/'resume.docx'; d=Document(); d.add_paragraph('Python developer'); t=d.add_table(rows=1,cols=2); t.cell(0,0).text='Skill'; t.cell(0,1).text='Docker'; d.save(p)
 r=ResumeDocumentParser().parse(p); assert r.source_format=='docx' and 'Python developer' in r.text and 'Docker' in r.text

def test_pdf_text(tmp_path):
 p=tmp_path/'resume.pdf'; c=Canvas(str(p)); c.drawString(72,750,'Python developer with Docker, FastAPI, LangChain and PyTorch project experience.'); c.drawString(72,730,'Bachelor of Computer Science in Software Engineering.'); c.save()
 r=ResumeDocumentParser(minimum_pdf_characters=20).parse(p); assert r.source_format=='pdf' and 'Python developer' in r.text

def test_plain_text(tmp_path):
 p=tmp_path/'resume.txt'; p.write_text('Python and Docker'); assert 'Docker' in ResumeDocumentParser().parse(p).text
