class Source:
    """A source drives a Pipeline until cancelled.

    Implement `run(pipeline)`: call pipeline.connection(True/False, msg) for link
    state and pipeline.accept(line) / pipeline.accept_record(record) for data.
    `label` is recorded in the log header.
    """
    label = 'source'

    async def run(self, pipeline):
        raise NotImplementedError
