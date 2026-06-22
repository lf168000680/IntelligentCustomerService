# 惰性导入，避免在无数据库环境导入失败
def get_core_engine():
    from .core import CoreEngine
    return CoreEngine

def get_intent_classifier():
    from .intent import IntentClassifier
    return IntentClassifier

def get_rag_retriever():
    from .rag import RAGRetriever
    return RAGRetriever

from .persona import PersonaBuilder, get_persona
