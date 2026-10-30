from pathlib import Path
from code_search_mcp.parsers.dispatcher import TreeSitterParser
from code_search_mcp.parsers.common import EXTENSION_LANG_MAP


def test_svelte_parsing_and_symbol_extraction():
    parser = TreeSitterParser()
    assert ".svelte" in EXTENSION_LANG_MAP
    assert EXTENSION_LANG_MAP[".svelte"] == "svelte"

    sample_svelte = """<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchUserProfile, logoutSession } from '@/services/auth';

  export let userId: string = '';
  let profile = null;

  async function loadProfile() {
    profile = await fetchUserProfile(userId);
  }

  function handleLogout() {
    logoutSession();
  }

  onMount(() => {
    loadProfile();
  });
</script>

<div class="user-profile">
  <h1>User Profile</h1>
  <button on:click={loadProfile}>Reload</button>
  <button onclick={handleLogout}>Logout</button>
  <input bind:value={userId} />
  <UserProfileCard {profile} />
</div>
"""
    symbols = parser.parse_code(sample_svelte.encode("utf-8"), "components/UserProfile.svelte", lang="svelte")
    assert len(symbols) >= 3, f"Expected at least 3 symbols, got {len(symbols)}"

    comp_sym = next((s for s in symbols if s.symbol_type == "component"), None)
    assert comp_sym is not None
    assert comp_sym.name == "UserProfile"
    assert "loadProfile" in comp_sym.calls
    assert "handleLogout" in comp_sym.calls
    assert "UserProfileCard" in comp_sym.calls

    fn_load = next((s for s in symbols if s.name == "loadProfile"), None)
    assert fn_load is not None
    assert fn_load.symbol_type == "function"
    assert fn_load.start_line >= 8  # Aligned line number inside <script>
    assert "fetchUserProfile" in fn_load.calls

    fn_logout = next((s for s in symbols if s.name == "handleLogout"), None)
    assert fn_logout is not None
    assert "logoutSession" in fn_logout.calls
