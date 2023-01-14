#!/usr/bin/env python3

"""
An object that maintains questions and answers for a simple,
hopefully non-annoying captcha (no "click on road signs", I promise!)

ChattyCaptcha is a singleton; call random_question() to get a question,
then pass that question back for is_answer_correct().
You shouldn't need to create your own ChattyCaptcha object
or reference the one defined here.

ChattyCaptcha uses questions from a questionfile in the following
human-readable format:

What's the best computer language?
python
c

What's the brightest star?
sirius
sun
the sun
sol

What's three squared?
9
nine

Comments begin with #. Blank lines separate questions.
Answers are case insensitive.
"""

import sys, os
import random
import json


#####################################################
# PUBLIC API
#####################################################

def init_captcha(questionfile):
    captcha.initialize(questionfile)


def initialized():
    try:
        return len(captcha.QandA.keys()) > 1
    except:
        return False


def random_question(current_question=None):
    """Return a randomly chosen question (different from the current one)
       and set self.current_question to it.
    """
    return captcha.random_question(current_question)


def is_answer_correct(answer, question):
    return captcha.is_answer_correct(answer, question)


#####################################################
# Not intended to be public
#####################################################

class ChattyCaptcha:
    """Take a list of questions, each with one or more valid answers,
       from a file. Offer a way to choose random questions, and to
       check answers against the last question presented.

       You can test a ChattyCaptcha object's truth value to see if it
       has questions: if not chatty_captcha: print("No questions file")
    """

    def __init__(self):
        self.filename = None
        self.QandA = None

    def initialize(self, questionfile):
        self.filename = questionfile
        self.QandA = None

        random.seed()

        self.read_question_file()

    def __bool__(self):
        if self.QandA:
            return True
        return False

    def random_question(self, current_question=None):
        if not self.QandA:
            raise RuntimeError("Need to initialize the captcha with a file")

        if len(self.QandA) <= 1:
            print("Captcha doesn't have enough questions:", self.QandA,
                  file=sys.stderr)
            raise RuntimeError("Captcha doesn't have enough questions")

        oldq = current_question
        while True:
            question = random.choice(list(self.QandA))
            if question == oldq:
                continue
            return question

    def is_answer_correct(self, ans, question):
        """Does ans match any of the answers for the given question?
           If question is unspecified, use self.current_question.
           Case insensitive.
           Returns a Boolean.
        """
        # If there are no questions, consider all answers correct
        if not self.QandA:
            return True

        if not question:
            question = self.current_question

        # Bots can send random answers as form field data,
        # which will raise a KeyError since the capq.data
        # may not be one of the valid questions.
        if question not in self.QandA:
            print("BOT ALERT: '%s' wasn't one of the questions" % question,
                  file=sys.stderr)
            return False

        return ans.lower() in self.QandA[question]

    def read_question_file(self):
        """Initialize the questions and their answers.
        """
        self.QandA = {}

        if not self.filename:
            return

        cur_question = None
        try:
            with open(self.filename) as fp:
                for line in fp:
                    line = line.strip()

                    if line.startswith('#'):
                        continue

                    if not line:
                        cur_question = None
                        continue

                    if cur_question:
                        self.QandA[cur_question].append(line.lower())
                        continue

                    cur_question = line
                    self.QandA[cur_question] = []
        except:
            return


# The singleton
captcha = ChattyCaptcha()


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print("Usage: %s question_file" % os.path.basename(sys.argv[0]))
        sys.exit(1)

    init_captcha(sys.argv[1])
    try:
        while True:
            print()
            question = random_question()
            print(question)
            answer = input()
            if is_answer_correct(answer, question):
                print("Yes!")
            else:
                print("Sorry, no.")

    except (KeyboardInterrupt, EOFError):
        print("\nBye!")
