# App structure

`apps/g1_control_test.py` and `apps/g1_conversation_test.py` preserve working PC behavior. `apps/g1_control.py` and `apps/g1_conversation.py` are the physical G1 deployment versions. The physical control file includes action discovery, bounded command dispatch, host/robot PCM input, and onboard TTS. The physical conversation file imports audio helpers from it but never connects motion services.

Vision stays separate in `apps/vision/`. See `G1_FIRST_CONNECTION.md` for limitations and test order. Shared asset, test, documentation, model and third-party repository folders remain in place.
