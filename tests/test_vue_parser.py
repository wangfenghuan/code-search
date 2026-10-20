from pathlib import Path
from code_search_mcp.parsers.dispatcher import TreeSitterParser
from code_search_mcp.parsers.common import EXTENSION_LANG_MAP


def test_vue_parsing_and_symbol_extraction():
    parser = TreeSitterParser()
    assert ".vue" in EXTENSION_LANG_MAP
    assert EXTENSION_LANG_MAP[".vue"] == "vue"

    sample_vue = """<template>
  <div class="login-view">
    <h1>Login</h1>
    <button @click="handleLogin">Submit</button>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { loginApi } from '@/api/auth';

const username = ref('');

function handleLogin() {
  loginApi(username.value);
}
</script>
"""
    symbols = parser.parse_code(sample_vue.encode("utf-8"), "views/Login.vue", lang="vue")
    assert len(symbols) >= 2, f"Expected at least 2 symbols, got {len(symbols)}"
    
    comp_sym = next((s for s in symbols if s.symbol_type == "component"), None)
    assert comp_sym is not None
    assert comp_sym.name == "Login"
    assert "handleLogin" in comp_sym.calls

    fn_sym = next((s for s in symbols if s.name == "handleLogin"), None)
    assert fn_sym is not None
    assert fn_sym.symbol_type == "function"
    assert fn_sym.start_line >= 13  # Aligned line number inside <script setup>
