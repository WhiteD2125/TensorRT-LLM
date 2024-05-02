import random

import click
from utils.utils import dataset_dump, gen_random_tokens, get_norm_dist_tokens


@click.command()
@click.option("--num-requests",
              required=True,
              type=int,
              help='Number of requests to be generated')
@click.option('--input-mean',
              required=True,
              type=int,
              help='normal dist mean for input tokens')
@click.option('--input-stdev',
              required=True,
              type=int,
              help='normal dist stdev for input tokens')
@click.option('--output-mean',
              required=True,
              type=int,
              help='normal dist mean for output tokens')
@click.option('--output-stdev',
              required=True,
              type=int,
              help='normal dist stdev for output tokens')
@click.pass_obj
def token_norm_dist(root_args, **kwargs):
    """Prepare dataset by generating random tokens."""
    input_ids = []
    input_lens = []
    output_lens = []
    task_ids = []

    input_lens = get_norm_dist_tokens(kwargs['input_mean'],
                                      kwargs['input_stdev'],
                                      kwargs['num_requests'],
                                      root_args.random_seed)

    num_reqs = len(input_lens)
    output_lens = get_norm_dist_tokens(kwargs['output_mean'],
                                       kwargs['output_stdev'], num_reqs,
                                       root_args.random_seed)

    max_input_len = max(input_lens)
    max_output_len = max(output_lens)

    input_ids = gen_random_tokens(input_lens, root_args.tokenizer,
                                  root_args.random_seed)

    if root_args.rand_task_id is None:
        task_ids = [root_args.task_id for _ in range(num_reqs)]
    else:
        min_id, max_id = root_args.rand_task_id
        task_ids = [random.randint(min_id, max_id) for _ in range(num_reqs)]

    dataset_dump(
        input_lens, input_ids, output_lens, task_ids, {
            "workload_type": "token-norm-dist",
            "input_mean": kwargs['input_mean'],
            "input_stdev": kwargs['input_stdev'],
            "output_mean": kwargs['output_mean'],
            "output_stdev": kwargs['output_stdev'],
            "num_requests": kwargs['num_requests'],
            "tokenize_vocabsize": root_args.tokenizer.vocab_size,
            "max_input_len": max_input_len,
            "max_output_len": max_output_len
        }, root_args.output)
