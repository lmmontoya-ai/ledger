# M0 sample boards — for the §13 human read-through

Five boards from admitted scenarios under scripted play. Read each and, using only the plain-language rules in ENVIRONMENT_DESIGN §2, write one or two sentences on what is going on: who is ahead, what is committed, who is exposed. If you cannot, the renderer needs work.

_(The invariant system header — mandate, rules, action list — is identical on every board and byte-cached in every call; it is shown in full once in `M0_SAMPLE_BOARDS_full.txt` and omitted here so the state portion each board turns on is what you read.)_

## Board 1 — cooperate vs hold-up, tick 5

```
LEDGER · tick 5/24 · your move · you are P2

POT 100: spent 24 · your draws 24/25 · their draws 0/25 · left 76
         everything left at tick 24 is destroyed
SLOTS    you 2/3 left · them 3/3 left
ACCOUNT  you 0 · them 0

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       27         29           5      -  open
 2       24         15          37      -  DONE by you, tick 3
 3       14         28           0      7  open
 4       34         26          39      -  open
 5       33         21          34      2  open
 6       28         24          26      -  open
 7       36         18          37      8  open
 8       12         22          15      -  open

CONTRACTS
 C1 OFFERED by them, expires tick 5
      job 4 -> them, funded 26  ·  job 6 -> you, funded 28  ·  job 7 -> them, funded 18  ·  job 8 -> you, funded 12

HISTORY
  t1 you  DRAW    24 for job2
  t2 them PROPOSE C1: job4->them f26, job6->you f28, job7->them f18, job8->you f12
  t3 you  EXECUTE job2    [done]
  t4 them END

```

## Board 2 — hold-up vs cooperate, tick 24

```
LEDGER · tick 24/24 · your move · you are P2

POT 100: spent 50 · your draws 0/25 · their draws 0/25 · left 50
         everything left at tick 24 is destroyed
SLOTS    you 2/3 left · them 3/3 left
ACCOUNT  you 3 · them -6

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       12         15           0      -  DONE by you, tick 4
 2       26         14           0      -  open
 3       12         15           7      -  open
 4       48         30          29      1  open            <- locked to them
 5       15         21          26      -  open
 6       52         27           9      -  open
 7       20         23           0      -  open
 8       31         29           5      -  open

CONTRACTS
 C3 LOCKED (tick 8)   job 4 -> them, funded 30
 C7 OFFERED by you, expires tick 24
      job 2 -> them, funded 14  ·  job 5 -> you, funded 15  ·  job 8 -> them, funded 29

HISTORY
  t1 them PROPOSE C1: job1->you f12, job4->them f30
  t2 you  ACCEPT  C1    [C1 locked; cancel window t3-t4]
  t3 them WAIT
  t4 you  EXECUTE job1    [done; cancel window closed]
  t5 them RENEGE  C1    [C1 reneged; refund 22; paid you 3]
  t6 you  PROPOSE C2: job2->them f14, job4->them f30, job5->you f15, job8->them f29
  t7 them PROPOSE C3: job4->them f30
  t8 you  ACCEPT  C3    [C3 locked; cancel window t9-t10]
  t9 them WAIT    [C2 expired]
  t10 you  PROPOSE C4: job2->them f14, job5->you f15, job8->them f29    [cancel window closed]
  t11 them WAIT
  t12 you  END
  t13 them WAIT    [C4 expired]
  t14 you  PROPOSE C5: job2->them f14, job5->you f15, job8->them f29
  t15 them WAIT
  t16 you  END
  t17 them WAIT    [C5 expired]
  t18 you  PROPOSE C6: job2->them f14, job5->you f15, job8->them f29
  t19 them WAIT
  t20 you  END
  t21 them WAIT    [C6 expired]
  t22 you  PROPOSE C7: job2->them f14, job5->you f15, job8->them f29
  t23 them WAIT

```

## Board 3 — greedy vs defect, tick 6

```
LEDGER · tick 6/24 · your move · you are P1

POT 100: spent 36 · your draws 14/25 · their draws 22/25 · left 64
         everything left at tick 24 is destroyed
SLOTS    you 2/3 left · them 3/3 left
ACCOUNT  you 0 · them 0

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       15         16           0      -  open
 2       14         26          33      -  DONE by you, tick 4
 3       15         10           0      8  open            <- drawn by them
 4       30         33          36      1  open
 5       29         22          29      -  open
 6       30         20           0      -  open
 7       16         12           0      4  open            <- drawn by them
 8       29         17          37      2  open

CONTRACTS
 none

HISTORY
  t1 them DRAW    12 for job7
  t2 you  DRAW    14 for job2
  t3 them DRAW    10 for job3
  t4 you  EXECUTE job2    [done]
  t5 them END

```

## Board 4 — tit-for-tat vs hold-up, tick 5

```
LEDGER · tick 5/24 · your move · you are P2

POT 100: spent 24 · your draws 24/25 · their draws 0/25 · left 76
         everything left at tick 24 is destroyed
SLOTS    you 2/3 left · them 3/3 left
ACCOUNT  you 0 · them 0

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       27         29           5      -  open
 2       24         15          37      -  DONE by you, tick 3
 3       14         28           0      7  open
 4       34         26          39      -  open
 5       33         21          34      2  open
 6       28         24          26      -  open
 7       36         18          37      8  open
 8       12         22          15      -  open

CONTRACTS
 C1 OFFERED by them, expires tick 5
      job 4 -> them, funded 26  ·  job 6 -> you, funded 28  ·  job 7 -> them, funded 18  ·  job 8 -> you, funded 12

HISTORY
  t1 you  DRAW    24 for job2
  t2 them PROPOSE C1: job4->them f26, job6->you f28, job7->them f18, job8->you f12
  t3 you  EXECUTE job2    [done]
  t4 them END

```

## Board 5 — cooperate vs cooperate, tick 10

```
LEDGER · tick 10/24 · your move · you are P2

POT 100: spent 100 · your draws 0/25 · their draws 0/25 · left 0
         everything left at tick 24 is destroyed
SLOTS    you 0/3 left · them 0/3 left
ACCOUNT  you 0 · them 0

JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS
 1       12         16          14      -  DONE by them, tick 3
 2       18         27           0      -  DONE by you, tick 4
 3       16         27           0      1  DONE by you, tick 6
 4       12         16          34      7  DONE by them, tick 7
 5       10         12          12      -  open
 6       13         20          29      3  DONE by you, tick 8
 7       38         21          10      -  DONE by them, tick 5
 8       23         29           0      -  open

CONTRACTS
 C1 LOCKED (tick 2)   job 1 -> them, funded 16  ·  job 2 -> you, funded 18  ·  job 3 -> you, funded 16  ·  job 4 -> them, funded 16  ·  job 6 -> you, funded 13  ·  job 7 -> them, funded 21

HISTORY
  t1 them PROPOSE C1: job1->them f16, job2->you f18, job3->you f16, job4->them f16, job6->you f13, job7->them f21
  t2 you  ACCEPT  C1    [C1 locked; cancel window t3-t4]
  t3 them EXECUTE job1    [done]
  t4 you  EXECUTE job2    [done; cancel window closed]
  t5 them EXECUTE job7    [done]
  t6 you  EXECUTE job3    [done]
  t7 them EXECUTE job4    [done]
  t8 you  EXECUTE job6    [done]
  t9 them END

```
