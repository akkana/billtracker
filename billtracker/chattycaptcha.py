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

       You can test a ChattyCaptcha object's truth value to see if it
       has questions: if not chatty_captcha: print("No questions file")
    """

    def __init__(self, questionfile):
        self.filename = questionfile
        self.QandA = None
        self.current_question = None

        random.seed()

        self.read_question_file()

    def __bool__(self):
        if self.QandA:
            return True
        return False

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

    def random_question(self):
        """Return a randomly chosen question (different from the current one)
           and set self.current_question to it.
        """
        if not self:
            return ""

        oldq = self.current_question
        while self.current_question == oldq:
            self.current_question = random.choice(list(self.QandA))
            if len(self.QandA) == 1:
                break

        return self.current_question

    def is_answer_correct(self, ans, question=None):
        """Does ans match any of the answers for the given question?
           If question is unspecified, use self.current_question.
           Case insensitive.
           Returns a Boolean.
        """
        # If there are no questions, consider all answers correct
        if not self:
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
    except (KeyboardInterrupt, EOFError):
        print("\nBye!")
