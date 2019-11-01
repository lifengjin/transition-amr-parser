# AMR parsing given a sentence and a model
import time
import os
import signal
import argparse
from collections import Counter, defaultdict

import numpy as np
from tqdm import tqdm

from transition_amr_parser.state_machine import AMRStateMachine
from transition_amr_parser.io import (
    writer,
    read_sentences,
    read_rule_stats,
)


# is_url_regex = re.compile('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')


def argument_parser():

    parser = argparse.ArgumentParser(description='AMR parser')
    # Multiple input parameters
    parser.add_argument(
        "--in-sentences",
        help="file space with carriare return separated sentences",
        type=str
    )
    parser.add_argument(
        "--in-actions",
        help="file space with carriage return separated sentences",
        type=str
    )
    parser.add_argument(
        "--out-amr",
        help="parsing model",
        type=str
    )
    parser.add_argument(
        "--in-model",
        help="parsing model",
        type=str
    )
    # state machine rules
    parser.add_argument(
        "--action-rules-from-stats",
        help="Use oracle statistics to restrict possible actions",
        type=str
    )
    # Visualization arguments
    parser.add_argument(
        "--verbose",
        help="verbose mode",
        action='store_true',
        default=False
    )
    parser.add_argument(
        "--step-by-step",
        help="pause after each action",
        action='store_true',
        default=False
    )
    parser.add_argument(
        "--pause-time",
        help="time waited after each step, default is manual",
        type=int
    )
    parser.add_argument(
        "--clear-print",
        help="clear command line before each print",
        action='store_true',
        default=False
    )
    parser.add_argument(
        "--offset",
        help="start at given sentence number (starts at zero)",
        type=int
    )
    parser.add_argument(
        "--random-up-to",
        help="sample randomly from a max number",
        type=int
    )
    parser.add_argument(
        "--no-whitespace-in-actions",
        action='store_true',
        help="Assume whitespaces normalized to _ in PRED"
    )

    args = parser.parse_args()

    # Argument pre-processing
    if args.random_up_to:
        args.offset = np.random.randint(args.random_up_to)

    # force verbose
    if not args.verbose:
        args.verbose = bool(args.step_by_step)

    # Sanity checks
    assert args.in_sentences or args.in_sentence_list
    assert args.in_actions or args.in_model
    # Not done yet
    if args.in_model:
        raise NotImplementedError()

    return args


def reduce_counter(counts, reducer):
    """
    Returns a new counter from an existing one where keys have been mapped
    to in  many-to-one fashion and counts added
    """
    new_counts = Counter()
    for key, count in counts.items():
        new_key = reducer(key)
        new_counts[new_key] += count
    return new_counts


class AMRParser():

    def __init__(self, model_path=None, verbose=False, logger=None):

        # TODO: Real parsing model
        raise NotImplementedError()

        self.rule_stats = read_rule_stats(f'{model_path}/train.rules.json')
        self.model = None
        self.logger = logger
        self.sent_idx = 0

    def parse_sentence(self, sentence_str):

        # TODO: Tokenizer
        tokens = sentence_str.split()

        # Initialize state machine
        state_machine = AMRStateMachine(tokens)

        # execute parsing model
        while not state_machine.is_closed:

            # TODO: get action from model
            raw_action = None

            # Inform user
            self.logger.pretty_print(self.sent_idx, state_machine)

            # Update state machine
            state_machine.applyAction(raw_action)

        self.sent_idx += 1

        return state_machine.amr


class FakeAMRParser():
    """
    Fake parser that uses precomputed sequences of sentences and corresponding
    actions
    """

    def __init__(self, from_sent_act_pairs=None, logger=None,
                 actions_by_stack_rules=None, no_whitespace_in_actions=False):

        # Dummy mode: simulate parser from pre-computed pairs of sentences
        # and actions
        self.actions_by_sentence = {
            sent: actions for sent, actions in from_sent_act_pairs
        }
        self.logger = logger
        self.sent_idx = 0
        self.actions_by_stack_rules = actions_by_stack_rules
        self.no_whitespace_in_actions = no_whitespace_in_actions

        self.pred_counts = Counter()

    def parse_sentence(self, sentence_str):

        # simulated actions given by a parsing model
        assert sentence_str in self.actions_by_sentence, \
            "Fake parser has no actions for sentence: %s" % sentence_str
        actions = self.actions_by_sentence[sentence_str].split()

        # Fake tokenization
        tokens = sentence_str.split()

        # Initialize state machine
        state_machine = AMRStateMachine(tokens)

        # execute parsing model
        while not state_machine.is_closed:

            # get action from model
            raw_action = actions[state_machine.time_step]

            if self.no_whitespace_in_actions and raw_action.startswith('PRED'):
                raw_action = raw_action.replace('_', ' ')

            # constrain action space if solicited
            if raw_action.startswith('PRED') and self.actions_by_stack_rules:
                node = raw_action[5:-1]
                token, merged_tokens = state_machine.get_top_of_stack()
                if merged_tokens:
                    token = ",".join(merged_tokens)
                if token not in self.actions_by_stack_rules:
                    raw_action = f'PRED({token.lower()})'
                    self.pred_counts.update(['token OOV'])
                elif node not in self.actions_by_stack_rules[token].keys():    
                    new_node = self.actions_by_stack_rules[token].most_common(1)[0][0]
                    raw_action = f'PRED({new_node})'
                    self.pred_counts.update(['alignment OOV'])
                else:
                    self.pred_counts.update(['matches'])

            # Print state (pause if solicited)
            self.logger.update(self.sent_idx, state_machine)

            # Update state machine
            state_machine.applyAction(raw_action)

        # count one sentence more
        self.sent_idx += 1

        return state_machine.amr


class Logger():

    def __init__(self, step_by_step=None, clear_print=None, pause_time=None,
                 verbose=False):

        self.step_by_step = step_by_step
        self.clear_print = clear_print
        self.pause_time = pause_time
        self.verbose = verbose or self.step_by_step

        if step_by_step:

            # Set traps for system signals to die graceful when Ctrl-C used

            def ordered_exit(signum, frame):
                """Mesage user when killing by signal"""
                print("\nStopped by user\n")
                exit(0)

            signal.signal(signal.SIGINT, ordered_exit)
            signal.signal(signal.SIGTERM, ordered_exit)

    def update(self, sent_idx, state_machine):

        if self.verbose:
            if self.clear_print:
                # clean screen each time
                os.system('clear')
            print(f'sentence {sent_idx}\n')
            print(state_machine)
            # step by step mode
            if self.step_by_step:
                if self.pause_time:
                    time.sleep(self.pause_time)
                else:
                    input('Press any key to continue')


def main():

    # Argument handling
    args = argument_parser()

    # Get data
    sentences = read_sentences(args.in_sentences)

    # Initialize logger/printer
    logger = Logger(
        step_by_step=args.step_by_step,
        clear_print=args.clear_print,
        pause_time=args.pause_time,
        verbose=args.verbose
    )

    # generate rules to restrict action space by stack content
    if args.action_rules_from_stats:
        rule_stats = read_rule_stats(args.action_rules_from_stats)
        actions_by_stack_rules = rule_stats['possible_predicates']
        for token, counter in rule_stats['possible_predicates'].items():
            actions_by_stack_rules[token] = Counter(counter)

    else:    
        actions_by_stack_rules = None

    # Load real or dummy Parsing model
    if args.in_actions:

        # Fake parser built from actions
        actions = read_sentences(args.in_actions)
        assert len(sentences) == len(actions)
        parsing_model = FakeAMRParser(
            from_sent_act_pairs=zip(sentences, actions),
            logger=logger,
            actions_by_stack_rules=actions_by_stack_rules,
            no_whitespace_in_actions=args.no_whitespace_in_actions
        )

    else:
        # TODO: Real parsing model
        raise NotImplementedError()
        parsing_model = AMRParser(logger=logger)

    # Get output AMR writer
    if args.out_amr:
        amr_write = writer(args.out_amr)

    # Loop over sentences
    for sent_idx, sentence in tqdm(enumerate(sentences)):

        # fast-forward until desired sentence number
        if args.offset and sent_idx < args.offset:
            continue

        # parse
        amr = parsing_model.parse_sentence(sentence)

        # store output AMR
        if args.out_amr:
            amr_write(amr.toJAMRString())

    if args.action_rules_from_stats:
        print("Predict rules had following statistics")
        print(parsing_model.pred_counts)

    # close output AMR writer
    if args.out_amr:
        amr_write()
