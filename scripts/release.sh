#!/usr/bin/env bash
set -euo pipefail

# ── Colores ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}==> ${NC}$1"; }
ok()    { echo -e "${GREEN}==> ${NC}$1"; }
warn()  { echo -e "${YELLOW}==> ${NC}$1"; }
fail()  { echo -e "${RED}==> ERROR: ${NC}$1"; exit 1; }

# ── Navegar al root del repo ─────────────────────────────────────────────────
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "No es un repositorio git."
cd "$REPO_ROOT"

echo ""
echo -e "${BOLD}Claude Monitor — Release Script${NC}"
echo "────────────────────────────────────────"
echo ""

# ── 1. Verificar rama ────────────────────────────────────────────────────────
BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" != "main" ]]; then
    warn "Estas en la rama '${BRANCH}', no en 'main'."
    read -rp "Continuar de todos modos? [y/N] " yn
    [[ "$yn" =~ ^[Yy]$ ]] || exit 0
fi

# ── 2. Mostrar estado del working tree ───────────────────────────────────────
if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
    ok "Working tree limpio."
else
    echo -e "${BOLD}Cambios pendientes (se incluiran en el commit):${NC}"
    echo ""
    git status --short
    echo ""
fi

# ── 3. Correr tests ─────────────────────────────────────────────────────────
info "Corriendo tests..."
if uv run pytest --tb=short -q 2>&1; then
    ok "Tests OK."
else
    fail "Los tests fallaron. Corregir antes de publicar."
fi
echo ""

# ── 4. Version actual ───────────────────────────────────────────────────────
CURRENT_VERSION="$(python3 -c "
import re
text = open('claude_monitor/__init__.py').read()
print(re.search(r'__version__\s*=\s*\"(.+?)\"', text).group(1))
")"
ok "Version actual: ${BOLD}${CURRENT_VERSION}${NC}"

# Sugerir siguiente version (patch bump por defecto)
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
SUGGESTED_PATCH="$MAJOR.$MINOR.$((PATCH + 1))"
SUGGESTED_MINOR="$MAJOR.$((MINOR + 1)).0"
SUGGESTED_MAJOR="$((MAJOR + 1)).0.0"

echo ""
echo "  Sugerencias:"
echo "    patch: $SUGGESTED_PATCH"
echo "    minor: $SUGGESTED_MINOR"
echo "    major: $SUGGESTED_MAJOR"
echo ""

# ── 5. Pedir nueva version ──────────────────────────────────────────────────
read -rp "Nueva version (o Enter para $SUGGESTED_PATCH): " NEW_VERSION
NEW_VERSION="${NEW_VERSION:-$SUGGESTED_PATCH}"

# Validar formato semver
if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    fail "Version '$NEW_VERSION' no tiene formato valido (X.Y.Z)."
fi

# Verificar que sea mayor que la actual
NEWER="$(python3 -c "
cur = tuple(int(x) for x in '$CURRENT_VERSION'.split('.'))
new = tuple(int(x) for x in '$NEW_VERSION'.split('.'))
print('yes' if new > cur else 'no')
")"
if [[ "$NEWER" != "yes" ]]; then
    fail "La version $NEW_VERSION no es mayor que la actual ($CURRENT_VERSION)."
fi

# Verificar que el tag no exista
if git tag -l "v$NEW_VERSION" | grep -q .; then
    fail "El tag v$NEW_VERSION ya existe."
fi

echo ""

# ── 6. Pedir mensaje de commit ──────────────────────────────────────────────
read -rp "Mensaje de commit (o Enter para 'release: version $NEW_VERSION'): " COMMIT_MSG
COMMIT_MSG="${COMMIT_MSG:-"release: version $NEW_VERSION"}"
echo ""

# ── 7. Resumen y confirmacion ───────────────────────────────────────────────
echo -e "${BOLD}Resumen:${NC}"
echo "  Version:  $CURRENT_VERSION -> $NEW_VERSION"
echo "  Tag:      v$NEW_VERSION"
echo "  Commit:   $COMMIT_MSG"
echo "  Branch:   $BRANCH"
echo "  Push:     origin/$BRANCH + tag v$NEW_VERSION"

# Verificar submodulo docs/private
SUBMODULE_DIRTY=false
if [[ -d "docs/private" ]] && git -C docs/private diff --quiet 2>/dev/null; then
    : # limpio
elif [[ -d "docs/private" ]]; then
    SUBMODULE_DIRTY=true
    echo "  Submodulo: docs/private tiene cambios (se pushea tambien)"
fi

echo ""
read -rp "Proceder? [y/N] " yn
[[ "$yn" =~ ^[Yy]$ ]] || { echo "Cancelado."; exit 0; }
echo ""

# ── 8. Bump version en __init__.py ──────────────────────────────────────────
info "Bump __version__ -> $NEW_VERSION"
sed -i '' "s/__version__ = \".*\"/__version__ = \"$NEW_VERSION\"/" claude_monitor/__init__.py

# Verificar que el bump fue correcto
WRITTEN="$(python3 -c "
import re
text = open('claude_monitor/__init__.py').read()
print(re.search(r'__version__\s*=\s*\"(.+?)\"', text).group(1))
")"
if [[ "$WRITTEN" != "$NEW_VERSION" ]]; then
    fail "El bump fallo: __init__.py tiene '$WRITTEN' en vez de '$NEW_VERSION'."
fi
ok "Version bumped."

# ── 9. Commit ───────────────────────────────────────────────────────────────
info "Staging y commit..."
git add -A
git commit -m "$COMMIT_MSG"
ok "Commit creado."

# ── 10. Tag ─────────────────────────────────────────────────────────────────
info "Creando tag v$NEW_VERSION..."
git tag "v$NEW_VERSION"
ok "Tag v$NEW_VERSION creado."

# ── 11. Push submodulo si tiene cambios ─────────────────────────────────────
if [[ "$SUBMODULE_DIRTY" == true ]]; then
    info "Pusheando submodulo docs/private..."
    git -C docs/private add -A
    git -C docs/private commit -m "release: v$NEW_VERSION" || true
    git -C docs/private push origin main
    ok "Submodulo pusheado."
fi

# ── 12. Push rama + tag ────────────────────────────────────────────────────
info "Pusheando a origin..."
git push origin "$BRANCH"
git push origin "v$NEW_VERSION"
ok "Push completado."

echo ""
echo -e "${GREEN}${BOLD}Release v$NEW_VERSION publicada!${NC}"
echo ""
echo "  GitHub Actions va a:"
echo "    1. Build .app con PyInstaller"
echo "    2. Crear GitHub Release con ZIP + DMG"
echo "    3. Actualizar Homebrew tap automaticamente"
echo ""
echo "  Seguir progreso en:"
echo "    https://github.com/SirMatoran/claude-monitor/actions"
echo ""
