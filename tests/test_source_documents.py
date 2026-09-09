from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import pytest
from data_platform.source_documents import SourceDocument, SourceDocumentStore

def document(text="<html>fixture</html>"):
    return SourceDocument("PUBLIC_HTML","https://public.example/match",datetime(2026,9,8,9,tzinfo=timezone.utc),"text/html",text,"BROWSER_CAPTURE")

def test_append_only_source_document_idempotency_and_safety(database):
    store=SourceDocumentStore(database); source_id=store.append(document())
    assert store.append(document())==source_id
    with database.connection() as connection:
        with pytest.raises(Exception): connection.execute("UPDATE source_documents SET content_text='x'")
        with pytest.raises(Exception): connection.execute("DELETE FROM source_documents")
    with pytest.raises(ValueError): store.append(SourceDocument("PUBLIC_HTML","https://x/?token=no",datetime(2026,9,8,9,tzinfo=timezone.utc),"text/html","x","WEB_FETCH"))
    with pytest.raises(ValueError): store.append(SourceDocument("PUBLIC_HTML","https://x",datetime(2026,9,8,9,tzinfo=timezone.utc),"text/html","","WEB_FETCH"))
