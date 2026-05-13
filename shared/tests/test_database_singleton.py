import pytest
from retrieval_shared.database import Database

def test_database_is_singleton():
    db1 = Database("postgresql://user:pass@localhost/db")
    db2 = Database("postgresql://user:pass@localhost/db")
    assert db1 is db2
