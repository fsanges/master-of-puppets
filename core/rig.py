import json
import logging
import os
import time
from collections import OrderedDict

import maya.cmds as cmds

from icarus.core.icarusNode import IcarusNode
from icarus.modules import all_rig_modules
from icarus.config import default_modules
from icarus.core.fields import ObjectField
from icarus.utils.undo import undoable
import icarus.dag
import icarus.postscript
from shapeshifter import shapeshifter

logger = logging.getLogger(__name__)


class Rig(IcarusNode):

    modules_group = ObjectField()
    extras_group = ObjectField()
    skeleton_group = ObjectField()

    def __init__(self):
        super(Rig, self).__init__('RIG')

        if not self.is_initialized.get():
            self._create_basic_hierarchy()
            self._add_default_modules()
            self.is_initialized.set(True)

    @property
    def rig_modules(self):
        modules = []
        for node in cmds.listRelatives(self.modules_group.get()) or []:
            module_type = cmds.getAttr(node + '.module_type')
            module = all_rig_modules[module_type](node, rig=self)
            modules.append(module)

        sorted_modules = []
        while modules:
            module = modules.pop()
            self.sort_parent_module(module, modules, sorted_modules)

        return sorted_modules

    def sort_parent_module(self, module, modules, sorted_modules):
        parent_module = module.parent_module
        if parent_module in modules:
            modules.remove(parent_module)
            self.sort_parent_module(parent_module, modules, sorted_modules)
    
        sorted_modules.append(module)

    @property
    def skeleton(self):
        return list(reversed(cmds.listRelatives(self.skeleton_group.get(), allDescendents=True)))

    @property
    def build_nodes(self):
        all_nodes = cmds.ls('*')
        build_nodes = []
        for node in all_nodes:
            if cmds.attributeQuery('is_build_node', node=node, exists=True):
                build_nodes.append(node)
        return build_nodes

    def _create_basic_hierarchy(self):
        if not cmds.objExists('MODULES'):
            self.modules_group.set(
                cmds.createNode(
                    'transform',
                    name='MODULES',
                )
            )
            cmds.parent(self.modules_group.get(), 'RIG')
        if not cmds.objExists('EXTRAS'):
            self.extras_group.set(
                cmds.createNode(
                    'transform',
                    name='EXTRAS',
                )
            )
            cmds.parent(self.extras_group.get(), 'RIG')
        if not cmds.objExists('SKELETON'):
            self.skeleton_group.set(
                cmds.createNode(
                    'transform',
                    name='SKELETON',
                )
            )
            cmds.parent(self.skeleton_group.get(), 'RIG')

    def _add_default_modules(self):
        for module_type, data in default_modules.iteritems():
            self.add_module(module_type, **data)

    @undoable
    def add_module(self, module_type, *args, **kwargs):
        if self.is_built.get():
            raise RuntimeError('Cannot add module when the rig is built.')

        if module_type not in all_rig_modules:
            raise ValueError("Module Type {} is not valid".format(module_type))

        # instantiate the new module from the list of possible modules.
        kwargs['rig'] = self
        new_module = all_rig_modules[module_type](*args, **kwargs)

        return new_module

    def get_module(self, module_node_name):
        """Get a module instance from a node name.

        :param module_node_name: name of the module's node
        :type module_node_name: str
        """
        for module in self.rig_modules:
            if module.node_name == module_node_name:
                return module
        logger.warning("Found no module named {}.".format(module_node_name))

    @undoable
    def delete_module(self, module_node_name):
        """Delete a module.

        :param module_node_name: name of the module's node
        :type module_node_name: str
        """
        if self.is_built.get():
            logger.error('Cannot delete a module if the rig is built.')
            return

        module_to_del = self.get_module(module_node_name)
        deform_joints = module_to_del.deform_joints.get()
        for module in self.rig_modules:
            if module.parent_joint.get() in deform_joints:
                new_parent_joint = module_to_del.parent_joint.get()
                module.parent_joint.set(new_parent_joint)
                module.update()
        cmds.delete(module_to_del.node_name)
        cmds.delete(deform_joints)

    @undoable
    def build(self):
        start_time = time.time()
        icarus.postscript.run_scripts('pre_build')

        nodes_before_build = set(cmds.ls('*'))
        for module in self.rig_modules:
            logger.info("Building: " + module.node_name)
            module._build()

            # set the attributes state back to what it was before unbuilding
            for ctl in module.controllers.get():
                attributes_state = cmds.getAttr(ctl + '.attributes_state')
                if attributes_state:
                    attributes_state = json.loads(attributes_state)
                    icarus.attributes.set_attributes_state(ctl, attributes_state)
            cmds.setAttr(module.placement_group.get() + '.visibility', False)

        nodes_after_build = set(cmds.ls('*'))
        build_nodes = list(nodes_after_build - nodes_before_build)

        for module in self.rig_modules:
            for ctl in module.controllers.get():
                parent_spaces = cmds.getAttr(ctl + '.parent_space_data')
                if not parent_spaces:
                    continue

                # Restore parent spaces.
                # We use an OrderedDict to load saved data
                # in order to preserve the parents ordering.
                spaces = json.loads(
                    parent_spaces,
                    object_pairs_hook=OrderedDict
                )
                if not hasattr(spaces, 'get'):
                    # In case serialized data is bad or serialization
                    # changes along the way.
                    continue

                parents = spaces.get('parents', [])
                space_type = spaces.get('space_type', 'parent')
                if parents:
                    icarus.dag.create_space_switching(ctl, parents, space_type)

        icarus.postscript.run_scripts('post_build')

        self._tag_nodes_for_unbuild(build_nodes)
        tot_time = time.time() - start_time
        self.is_built.set(True)
        logger.info("Building the rig took {}s".format(tot_time))

    @undoable
    def unbuild(self):
        icarus.postscript.run_scripts('pre_unbuild')

        self.reset_pose()

        for module in self.rig_modules:
            for ctl in module.controllers.get():
                try:
                    shape_data = shapeshifter.get_shape_data(ctl)
                    cmds.setAttr(
                        ctl + '.shape_data',
                        json.dumps(shape_data),
                        type='string'
                    )
                except:
                    pass
                attributes_state = icarus.attributes.get_attributes_state(ctl)
                cmds.setAttr(
                    ctl + '.attributes_state',
                    json.dumps(attributes_state),
                    type='string'
                )
            cmds.setAttr(module.placement_group.get() + '.visibility', True)

        for node in self.skeleton:
            for attribute in ['.translate', '.rotate', '.scale']:
                attr = node + attribute
                input_attr = cmds.connectionInfo(attr, sourceFromDestination=True)
                cmds.disconnectAttr(input_attr, attr)
        cmds.delete(self.build_nodes)
        for module in self.rig_modules:
            module.is_built.set(False)

        self.is_built.set(False)
        icarus.postscript.run_scripts('post_unbuild')

    def publish(self):
        icarus.postscript.run_scripts('pre_publish')
        cmds.setAttr(self.skeleton_group.get() + '.visibility', False)
        for module in self.rig_modules:
            logger.info("Publishing: " + module.node_name)
            module.publish()
        icarus.postscript.run_scripts('post_publish')

    @undoable
    def reset_pose(self):
        for control in cmds.ls('*_ctl'):
            icarus.dag.reset_node(control)

    def _tag_nodes_for_unbuild(self, nodes):
        """Tag the nodes created during the build.

        this will allow to delete them easily later on.
        """
        for node in nodes:
            cmds.addAttr(
                node,
                longName='is_build_node',
                attributeType='bool',
                defaultValue=True
            )

