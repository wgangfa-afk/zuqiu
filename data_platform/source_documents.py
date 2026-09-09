"""Append-only intake for lawfully obtained public web and local source documents."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from .database import Database, normalize_utc, IdempotencyConflictError

@dataclass(frozen=True, slots=True)
class SourceDocument:
    source_type: str; source_url: str; retrieved_at_utc: datetime; content_type: str; content_text: str
    retrieval_method: str; published_at_utc: datetime | None = None; document_title: str | None = None
    parser_name: str | None = None; parser_version: str | None = None; validation_status: str = "RAW"; parent_document_id: str | None = None

class SourceDocumentStore:
    TYPES={"PUBLIC_HTML","PUBLIC_TEXT","JSON_LD","CSV_IMPORT","JSON_IMPORT","MANUAL_VERIFIED"}
    METHODS={"WEB_FETCH","BROWSER_CAPTURE","FILE_IMPORT","MANUAL_ENTRY"}
    def __init__(self,database:Database)->None:self.database=database
    def append(self,document:SourceDocument)->str:
        self.database._assert_writable()
        if document.source_type not in self.TYPES or document.retrieval_method not in self.METHODS or not document.content_text.strip(): raise ValueError("invalid source document")
        parsed=urlparse(document.source_url)
        if parsed.scheme not in {"http","https"} or not parsed.netloc or any(key.casefold() in {"token","apikey","api_key","authorization","cookie"} for key in parse_qs(parsed.query)): raise ValueError("unsafe source URL")
        if document.retrieved_at_utc.tzinfo is not timezone.utc or (document.published_at_utc and document.published_at_utc.tzinfo is not timezone.utc): raise ValueError("source timestamps must be UTC-aware")
        text=document.content_text; content_hash=hashlib.sha256(text.encode()).hexdigest(); key=hashlib.sha256((document.source_url+content_hash+document.retrieved_at_utc.isoformat()).encode()).hexdigest()
        fields=(document.source_type,document.source_url,parsed.netloc,normalize_utc(document.retrieved_at_utc.isoformat()),normalize_utc(document.published_at_utc.isoformat()) if document.published_at_utc else None,document.content_type,document.document_title,text,content_hash,document.parser_name,document.parser_version,document.validation_status,document.retrieval_method,document.parent_document_id,key)
        with self.database.connection() as connection:
            old=connection.execute("SELECT * FROM source_documents WHERE idempotency_key=?",(key,)).fetchone()
            if old:
                if old["content_sha256"] != content_hash: raise IdempotencyConflictError("source document idempotency conflict")
                return old["id"]
            document_id=str(uuid4()); connection.execute("INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",(document_id,*fields))
            return document_id
