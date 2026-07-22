#!/bin/bash

# Script to collect Deployment and ConfigMap YAMLs from a Kubernetes namespace
# Usage: ./collect_manifests.sh <namespace>
# Example: ./collect_manifests.sh dpikus-epd

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
print_section() { echo -e "${BLUE}[====]${NC} $1"; }

if [ -z "$1" ]; then
    print_error "Namespace not provided!"
    echo "Usage: $0 <namespace>"
    echo "Example: $0 dpikus-epd"
    exit 1
fi

NAMESPACE=$1

if ! command -v kubectl &> /dev/null; then
    print_error "kubectl is not installed or not in PATH"
    exit 1
fi

if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    print_error "Namespace '$NAMESPACE' does not exist"
    exit 1
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="manifests_${NAMESPACE}_${TIMESTAMP}"
DEPLOY_DIR="$OUTPUT_DIR/deployments"
CM_DIR="$OUTPUT_DIR/configmaps"
mkdir -p "$DEPLOY_DIR" "$CM_DIR"

CONTEXT=$(kubectl config current-context 2>/dev/null || echo "unknown")

print_info "Collecting manifests from namespace: $NAMESPACE"
print_info "kubectl context: $CONTEXT"
print_info "Output directory: $OUTPUT_DIR"
echo ""

# ---- Deployments -----------------------------------------------------------
print_section "Collecting Deployments"
DEPLOYMENTS=$(kubectl get deployments -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)

DEPLOY_COUNT=0
if [ -z "$DEPLOYMENTS" ]; then
    print_warning "No Deployments found in namespace '$NAMESPACE'"
else
    for D in $DEPLOYMENTS; do
        print_info "  Saving Deployment: $D"
        if kubectl get deployment "$D" -n "$NAMESPACE" -o yaml > "$DEPLOY_DIR/${D}.yaml" 2>/dev/null; then
            DEPLOY_COUNT=$((DEPLOY_COUNT + 1))
        else
            print_warning "    ✗ Failed to get Deployment '$D'"
            rm -f "$DEPLOY_DIR/${D}.yaml"
        fi
    done
    kubectl get deployments -n "$NAMESPACE" -o yaml > "$OUTPUT_DIR/all-deployments.yaml" 2>/dev/null || true
fi
echo ""

# ---- ConfigMaps ------------------------------------------------------------
print_section "Collecting ConfigMaps"
CONFIGMAPS=$(kubectl get configmaps -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)

CM_COUNT=0
if [ -z "$CONFIGMAPS" ]; then
    print_warning "No ConfigMaps found in namespace '$NAMESPACE'"
else
    for CM in $CONFIGMAPS; do
        print_info "  Saving ConfigMap: $CM"
        SAFE_NAME=$(echo "$CM" | tr '/' '_')
        if kubectl get configmap "$CM" -n "$NAMESPACE" -o yaml > "$CM_DIR/${SAFE_NAME}.yaml" 2>/dev/null; then
            CM_COUNT=$((CM_COUNT + 1))
        else
            print_warning "    ✗ Failed to get ConfigMap '$CM'"
            rm -f "$CM_DIR/${SAFE_NAME}.yaml"
        fi
    done
    kubectl get configmaps -n "$NAMESPACE" -o yaml > "$OUTPUT_DIR/all-configmaps.yaml" 2>/dev/null || true
fi
echo ""

# ---- Summary ---------------------------------------------------------------
SUMMARY_FILE="$OUTPUT_DIR/collection_summary.txt"
{
    echo "Manifest Collection Summary"
    echo "==========================="
    echo "Namespace:        $NAMESPACE"
    echo "kubectl context:  $CONTEXT"
    echo "Collection Time:  $(date)"
    echo "Deployments:      $DEPLOY_COUNT"
    echo "ConfigMaps:       $CM_COUNT"
    echo ""
    echo "Files:"
    echo "------"
    find "$OUTPUT_DIR" -type f -name "*.yaml" | sort | while read -r f; do
        size=$(du -h "$f" | cut -f1)
        echo "  ${f#$OUTPUT_DIR/}: $size"
    done
} > "$SUMMARY_FILE"

print_section "Collection Complete!"
print_info "Manifests saved to: $OUTPUT_DIR"
print_info "Summary saved to:   $SUMMARY_FILE"
echo ""
cat "$SUMMARY_FILE"

# ---- Tarball ---------------------------------------------------------------
TARBALL="${OUTPUT_DIR}.tar.gz"
print_info "Creating tarball: $TARBALL"
tar -czf "$TARBALL" "$OUTPUT_DIR" 2>/dev/null

if [ -f "$TARBALL" ]; then
    TARBALL_SIZE=$(du -h "$TARBALL" | cut -f1)
    print_info "✓ Tarball created successfully: $TARBALL ($TARBALL_SIZE)"
    echo ""
    print_info "To extract: tar -xzf $TARBALL"
else
    print_warning "Failed to create tarball"
fi
