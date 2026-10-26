from __future__ import annotations
import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from pypdf import PdfReader
from docx import Document

class ResumeParseError(RuntimeError): pass

@dataclass(frozen=True)
class ParsedResumeDocument:
    source_path: str
    source_format: str
    content_hash: str
    text: str
    page_count: int | None
    character_count: int
    extraction_method: str
    warnings: list[str]
    def to_dict(self): return asdict(self)

class ResumeDocumentParser:
    def __init__(self, *, minimum_pdf_characters: int = 80, max_characters: int = 120_000):
        self.minimum_pdf_characters=minimum_pdf_characters
        self.max_characters=max_characters

    def parse(self, path: str | Path) -> ParsedResumeDocument:
        p=Path(path).expanduser().resolve()
        if not p.exists() or not p.is_file(): raise ResumeParseError(f"Resume file not found: {p}")
        ext=p.suffix.lower()
        if ext=='.pdf': return self._pdf(p)
        if ext=='.docx': return self._docx(p)
        if ext=='.doc': return self._doc(p)
        if ext in {'.txt','.md'}: return self._plain(p)
        raise ResumeParseError(f"Unsupported resume format '{ext}'. Supported: .pdf, .docx, .doc, .txt, .md")

    def _hash(self,p):
        h=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
        return 'sha256:'+h.hexdigest()

    def _clean(self,text):
        text=text.replace('\x00','').replace('\r\n','\n').replace('\r','\n')
        lines=[re.sub(r'[ \t]+',' ',x).strip() for x in text.split('\n')]
        out=[]; blanks=0
        for line in lines:
            if not line:
                blanks+=1
                if blanks<=1: out.append('')
            else: blanks=0; out.append(line)
        return '\n'.join(out).strip()[:self.max_characters]

    def _pdf(self,p):
        try:
            reader=PdfReader(str(p)); pages=[]
            for i,page in enumerate(reader.pages,1): pages.append(f"[Page {i}]\n{page.extract_text() or ''}")
        except Exception as e: raise ResumeParseError(f"PDF extraction failed: {e}") from e
        text=self._clean('\n\n'.join(pages)); warnings=[]
        if len(re.sub(r'\s+','',text))<self.minimum_pdf_characters:
            raise ResumeParseError("PDF contains insufficient embedded text and likely requires OCR. OCR it first, then rerun resume ingestion.")
        return ParsedResumeDocument(str(p),'pdf',self._hash(p),text,len(reader.pages),len(text),'pypdf',warnings)

    def _docx(self,p):
        try: doc=Document(str(p))
        except Exception as e: raise ResumeParseError(f"DOCX extraction failed: {e}") from e
        parts=[]
        for para in doc.paragraphs:
            if para.text.strip(): parts.append(para.text)
        for ti,table in enumerate(doc.tables,1):
            parts.append(f"[Table {ti}]")
            for row in table.rows:
                cells=[self._clean(cell.text) for cell in row.cells]
                if any(cells): parts.append(' | '.join(cells))
        text=self._clean('\n'.join(parts))
        if not text: raise ResumeParseError('DOCX contains no extractable paragraph or table text.')
        return ParsedResumeDocument(str(p),'docx',self._hash(p),text,None,len(text),'python-docx',[])

    def _doc(self,p):
        warnings=[]
        soffice=shutil.which('libreoffice') or shutil.which('soffice')
        if soffice:
            with tempfile.TemporaryDirectory(prefix='jobmatch-doc-') as td:
                cp=subprocess.run([soffice,'--headless','--convert-to','docx','--outdir',td,str(p)],capture_output=True,text=True,timeout=90)
                converted=Path(td)/(p.stem+'.docx')
                if cp.returncode==0 and converted.exists():
                    result=self._docx(converted)
                    return ParsedResumeDocument(str(p),'doc',self._hash(p),result.text,None,len(result.text),'libreoffice-to-docx',warnings)
                warnings.append('LibreOffice conversion failed; trying antiword.')
        antiword=shutil.which('antiword')
        if antiword:
            cp=subprocess.run([antiword,str(p)],capture_output=True,text=True,timeout=60,errors='replace')
            text=self._clean(cp.stdout)
            if cp.returncode==0 and text:
                return ParsedResumeDocument(str(p),'doc',self._hash(p),text,None,len(text),'antiword',warnings)
        raise ResumeParseError('Legacy DOC parsing requires LibreOffice/soffice or antiword on PATH.')

    def _plain(self,p):
        text=self._clean(p.read_text(encoding='utf-8',errors='replace'))
        if not text: raise ResumeParseError('Resume text file is empty.')
        return ParsedResumeDocument(str(p),p.suffix.lower()[1:],self._hash(p),text,None,len(text),'plain-text',[])
