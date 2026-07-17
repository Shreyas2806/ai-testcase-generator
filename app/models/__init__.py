# Import all models here so SQLAlchemy's Base.metadata registry is fully
# populated before create_all() is called at startup.
#
# Order matters: parents must be imported before their children so that
# forward-reference strings (e.g. "Version") can be resolved correctly.

from app.models.document import Document          # root entity
from app.models.version import Version            # child of Document
from app.models.node import Node                  # child of Version
from app.models.selection import Selection        # independent entity
from app.models.selection_node import SelectionNode  # junction: Node <-> Selection
from app.models.node_diff import NodeDiff         # diff results between versions
from app.models.test_gen_result import TestGenResult  # LLM-generated test suites

__all__ = [
    "Document",
    "Version",
    "Node",
    "Selection",
    "SelectionNode",
    "NodeDiff",
    "TestGenResult",
]
