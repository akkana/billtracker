#!/usr/bin/env python3

"""
A ChattyCaptcha uses questions from a questionfile in the following
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

import sys
import random


class ChattyCaptcha:
    """Take a list of questions, each with one or more valid answers,
       from a file. Offer a way to choose random questions, and to
       check answers against the last question presented.
    """

    def __init__(self, questionfile):
        self.filename = questionfile
        self.QandA = None
        self.current_question = None

        self.read_question_file()

    def read_question_file(self):
        """Initialize the questions and their answers.
        """
        self.QandA = {}
        cur_question = None
        with open(self.filename) as fp:
            for line in fp:
                line = line.strip()

                if not line or line.startswith('#'):
                    cur_question = None
                    continue

                if cur_question:
                    self.QandA[cur_question].append(line.lower())
                    continue

                cur_question = line
                self.QandA[cur_question] = []

    def random_question(self):
        """Return a randomly chosen question,
           and set self.current_question to it.
        """
        self.current_question = random.choice(list(self.QandA))
        return self.current_question

    def is_answer_correct(self, ans):
        """Does ans match any of the answers for self.current_question?
           Case insensitive.
           Returns a Boolean.
        """
        return ans.lower() in self.QandA[self.current_question]


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print("Usage: %s question_file" % os.path.basename(sys.argv[0]))
        sys.exit(1)

    captcha = ChattyCaptcha(sys.argv[1])

    try:
        while True:
            print()
            print(captcha.random_question())
            ans = input()
            if captcha.is_answer_correct(ans):
                print("Yes!")
            else:
                print("Sorry, no.")
    except KeyboardInterrupt:
        print("\nBye!")
