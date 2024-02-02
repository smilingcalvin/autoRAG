from llama_index import VectorStoreIndex, SimpleDirectoryReader
from llama_index import StorageContext, load_index_from_storage
from llama_index import ServiceContext

from .process.azure.output import AzureOutputProcessor
from autorag.retriever.post_processors.node_expander import NodeExpander
import os, json

EMBED_MODEL_CONFIG_PATH = "embed_model_config.json"
STORAGE_BASENAME = "storage_context"
EXPANDED_NODE_BASENAME = "expanded_nodes"


class ExpandedIndexer:
    """A wrapper over data preprocessor, indexer and postprocessors for building, loading and persisting"""

    def __init__(self, index, node_expander):
        self.index = index
        self.node_expander = node_expander

    @classmethod
    def build(cls, data_dir, pre_processor_cfg, post_processor_cfg):
        # Processing documents based on the specified pre_processor type.
        sentence_splitter_cfg = pre_processor_cfg.sentence_splitter_cfg
        if pre_processor_cfg.pre_processor_type == "azure":
            file_type = pre_processor_cfg.azure_pre_processor_cfg.file_type
            include_table = pre_processor_cfg.azure_pre_processor_cfg.include_table
            nodes = AzureOutputProcessor(
                data_dir, file_type, sentence_splitter_cfg, include_table
            ).nodes
            index = VectorStoreIndex(nodes)
        else:
            documents = SimpleDirectoryReader(data_dir).load_data()
            service_context = ServiceContext.from_defaults(
                chunk_size=sentence_splitter_cfg.chunk_size,
                chunk_overlap=sentence_splitter_cfg.chunk_overlap,
            )
            index = VectorStoreIndex.from_documents(
                documents, service_context=service_context
            )

        if post_processor_cfg.enable_node_expander:
            node_expander = NodeExpander.build(
                index, post_processor_cfg.parent_metadata_field
            )
        else:
            node_expander = None

        return cls(index, node_expander)

    @classmethod
    def load(cls, index_dir, enable_node_expander=False):
        embed_model_config_path = ExpandedIndexer.get_embed_model_config_path(index_dir)
        from llama_index.embeddings.loading import load_embed_model

        with open(embed_model_config_path, "r", encoding="utf-8") as f:
            embed_model_config = json.loads(f.read())
        embed_model = load_embed_model(embed_model_config)
        service_context = ServiceContext.from_defaults(embed_model=embed_model)
        # rebuild storage context
        storage_context_dir = ExpandedIndexer.get_storage_context_dir(index_dir)
        storage_context = StorageContext.from_defaults(persist_dir=storage_context_dir)

        # load index
        index = load_index_from_storage(
            storage_context, service_context=service_context
        )
        if enable_node_expander:
            expanded_node_dir = ExpandedIndexer.get_expanded_node_dir(index_dir)
            node_expander = NodeExpander.load(expanded_node_dir)
        else:
            node_expander = None
        return cls(index, node_expander)

    def persist(self, index_dir):
        storage_context_dir = ExpandedIndexer.get_storage_context_dir(index_dir)
        expanded_node_dir = ExpandedIndexer.get_expanded_node_dir(index_dir)
        embed_model_config_path = ExpandedIndexer.get_embed_model_config_path(index_dir)

        self.index.storage_context.persist(persist_dir=storage_context_dir)
        if self.node_expander:
            self.node_expander.persist(expanded_node_dir)
        embed_model_config = self.index.service_context.embed_model.to_dict()
        embed_model_config.pop("api_key")
        with open(embed_model_config_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(embed_model_config))

    @staticmethod
    def get_storage_context_dir(index_dir):
        return os.path.join(index_dir, STORAGE_BASENAME)

    @staticmethod
    def get_expanded_node_dir(index_dir):
        return os.path.join(index_dir, EXPANDED_NODE_BASENAME)

    @staticmethod
    def get_embed_model_config_path(index_dir):
        return os.path.join(index_dir, EMBED_MODEL_CONFIG_PATH)
