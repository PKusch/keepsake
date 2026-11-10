# Security

keepsake is a gate between an AI agent and the files it uses as memory. A
report is in scope when it shows one of these:

- A change to a watched memory file takes effect without the person approving it.
- The guard lets a write through, or puts the wrong content back.
- A planted change in the shapes the corpus covers (fetch-and-run, sending
  things out, reading secrets, invisible characters, removing a rule that made
  the agent ask, copying itself into other memory, claiming the person agreed,
  misleading the person) scores below `high`.
- `keepsake approve` records something other than what `keepsake check` showed.

Out of scope, and said so in the README: a harmful instruction worded outside
the vocabulary scores `low`. It is still shown for approval, which is the floor
the tool promises. Memory kept somewhere other than files is not watched.

Report by opening an issue, or privately through GitHub's security advisory
form on this repository.
