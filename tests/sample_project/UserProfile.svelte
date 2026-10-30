<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchUserProfile, logoutSession } from './auth';

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
</div>
