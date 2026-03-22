"""Main entry point for docs2db MCP server."""

import asyncio
import logging
import os
import sys

# Read transport from env to decide logging strategy
transport = os.environ.get("DOCS2DB_MCP_TRANSPORT", "sse")

# Configure logging BEFORE importing heavy modules
if transport == "sse":
    # Normal logging for SSE mode
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )
else:
    # Silence all logging for stdio mode (stderr is MCP protocol)
    logging.disable(logging.CRITICAL)

# Import only config (lightweight)
# Defer heavy imports (engine, server) to main() for faster startup
from docs2db_mcp.config import CONFIG

logger = logging.getLogger(__name__)


async def cleanup() -> None:
    """Cleanup resources on shutdown."""
    logger.info("Shutting down docs2db MCP server")

    # Import engine only during cleanup to avoid startup overhead
    from docs2db_mcp.engine import shutdown_engine

    await shutdown_engine()


def main() -> None:
    """Run the MCP server."""
    # Import server here (tools are imported lazily by FastMCP)
    from docs2db_mcp.server import mcp

    # Configure structlog for stdio mode after server import
    if transport != "sse":
        import structlog

        def silent_processor(logger, method_name, event_dict):
            """Silent processor that returns empty string (structlog requires return value)."""
            return ""

        structlog.configure(processors=[silent_processor])

    logger.info(f"Starting docs2db MCP server on {CONFIG.host}:{CONFIG.port}")
    logger.info(f"Transport: {CONFIG.transport}")
    logger.info(f"Database: {CONFIG.db_host}:{CONFIG.db_port}/{CONFIG.db_database}")
    logger.info(f"RAG settings: threshold={CONFIG.rag_similarity_threshold}, "
                f"max_chunks={CONFIG.rag_max_chunks}, "
                f"reranking={CONFIG.rag_enable_reranking}")

    # Skip health check for stdio transport by default (for faster startup)
    # Set DOCS2DB_MCP_SKIP_HEALTH_CHECK=false to enable health check
    skip_health = CONFIG.skip_health_check or CONFIG.transport != "sse"

    if not skip_health:
        # Import health_check only when needed
        from docs2db_mcp.engine import health_check

        try:
            asyncio.run(health_check())
        except Exception as e:
            logger.error(f"Startup health check failed: {e}")
            logger.error("Server will not start - please check database connection and configuration")
            sys.exit(1)

    try:
        # Run the MCP server
        # Suppress banner in stdio mode - stdout is for MCP protocol only
        show_banner = CONFIG.transport == "sse"
        mcp.run(transport=CONFIG.transport, show_banner=show_banner, **CONFIG.transport_kwargs)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        asyncio.run(cleanup())


if __name__ == "__main__":
    main()