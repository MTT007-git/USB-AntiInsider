"""
Get a random key for authorization with a key
"""

import random

KEY_LEN = random.randint(64, 96)
KEY = ""
for i in range(KEY_LEN):
    scenario = random.randint(0, 2)
    if scenario == 0:
        KEY += chr(random.randint(ord("a"), ord("z")))
    elif scenario == 1:
        KEY += chr(random.randint(ord("A"), ord("Z")))
    else:
        KEY += chr(random.randint(ord("0"), ord("9")))

print(KEY)
