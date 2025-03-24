from .server import serve


def main():
    """MCP Search Server - Google search functionality for MCP"""
    import argparse
    import asyncio
    import logging

    parser = argparse.ArgumentParser(
        description="give a model the ability to perform Google searches"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Log to specified file instead of stderr"
    )
    parser.add_argument(
        "--cache-path",
        type=str,
        default="/app/cache/google_cache.db",
        help="Path to store search cache"
    )
    parser.add_argument(
        "--request-delay",
        type=int,
        default=5,
        help="Delay between search requests in seconds"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum number of retries for failed searches"
    )

    args = parser.parse_args()
    
    # Configure logging if log file is specified
    if args.log_file:
        logging.basicConfig(
            level=getattr(logging, args.log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            filename=args.log_file,
            filemode='a'
        )
        print(f"Logging to file: {args.log_file} at level {args.log_level}")
    else:
        logging.basicConfig(
            level=getattr(logging, args.log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    asyncio.run(serve(
        log_level=args.log_level,
        cache_path=args.cache_path,
        request_delay=args.request_delay,
        max_retries=args.max_retries
    ))


if __name__ == "__main__":
    main()