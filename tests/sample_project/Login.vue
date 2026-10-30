<template>
  <div class="login-view">
    <h1>Login</h1>
    <button @click="handleLogin">Submit</button>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { loginApi } from './auth';

const username = ref('');

function handleLogin() {
  loginApi(username.value);
}
</script>
