# 惰性导入，避免在无 pgvector 环境导入失败
def get_base():
    from .base import Base, engine, async_session, init_db, get_db, compute_embedding, compute_embeddings
    return Base, engine, async_session, init_db, get_db, compute_embedding, compute_embeddings

def get_models():
    from .models import (
        Conversation, UserProfile, KnowledgeItem, KnowledgeEmbedding,
        ConversationEmbedding, KnowledgeReview, KnowledgeGap, Product,
        LLMProviderRecord, PersonaRecord, DailyStats, AlertRecord,
    )
    return locals()

def get_vector_store():
    from .vector import VectorStore
    return VectorStore
