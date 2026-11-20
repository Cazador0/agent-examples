# Integration contract checklist

An integration bug is a disagreement between two sides about a contract. Before choosing a category, establish from evidence which side departed from the contract, or whether the contract itself was silent. Answer only the sections that apply, and write `Not provided` for what you could not see.

## Which side, which direction

- Who produced the message or request, and who consumed it?
- Is there a written contract (API specification, schema, interface agreement)? Quote the line that covers this case, or state that none does.
- Producer wrong, consumer wrong, or contract silent? Contract silent is `REQ`. One side departing from a clear contract is `INT`.

## JSON payloads

- Field present, absent or null, and does the contract distinguish these?
- Type and format: dates and time zones, decimals and rounding, booleans sent as strings.
- Code values: does each side map enumerations and type codes the same way?
- Does the consumer reject or ignore fields it does not know?
- Which schema version did each side use?

## REST APIs

- Method, path, status code and error body: expected against actual.
- Authentication and scopes for the calling identity in this environment.
- Paging, filtering and sorting on list calls.
- Retried calls: is the operation idempotent, or did a retry create a duplicate?
- Concurrent updates: was an optimistic-locking token such as a checksum or ETag sent and honoured?
- Timeouts and rate limits in UAT against those assumed in development.

## Kafka and other event streams

- Topic and partition key. Is ordering needed, and does the key guarantee it for this entity?
- Delivery is usually at least once. Does the consumer tolerate the same event twice?
- Serialization and schema compatibility between producer and consumer versions.
- Is the event a full snapshot or a change, and did the consumer assume the other?
- Consumer lag, replays, and what happens to a message that cannot be processed.

## Files, batch and SOAP

- Layout, encoding, delimiters and end-of-file handling.
- Schedule and time window; what happens on partial failure and on rerun.
- Service definition version on each side.

## Environment

- Endpoint, credentials and certificates configured for UAT.
- Feature flags and routing rules that differ from development.
- Whether the neighbouring system's UAT data matches this system's UAT data.

## Why it escaped

Most integration defects escape because the neighbour was mocked, and the mock agreed with the developer instead of the contract. Record what the mock returned and what the real system returned. The proposed test is usually a contract test that both sides run against the same specification.
